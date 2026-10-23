"""评测执行器:在指定分组下运行一个用例并录制全部工具输出。

- A:无 Skill(空视图),工具集合与 C 相同(五个核心工具)。
- B:全部 Skill 正文装入系统提示(不用渐进加载,不提供 Skill 视图)。
- C:主配置(简介发现 + read_file 按需加载;user_overrides 支持 Skill
  新旧版本比较,如 earnings-analysis→0.1.0 记为 C-old 配置)。
- D:确定性固定流程管道(仅 earnings 族;其余任务类型记 not_applicable)。

工具输出经录制包装全量保留,评分器据此核对引用与时间边界(§16.3)。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from finance_agent.adapters.engines.deepagents.agent import build_research_agent, make_ctx_factory
from finance_agent.adapters.engines.deepagents.checkpoints import open_sqlite_saver
from finance_agent.adapters.engines.deepagents.runner import run_config, stream_run
from finance_agent.adapters.engines.deepagents.tools import to_engine_tools
from finance_agent.bootstrap import build_default_registry
from finance_agent.budget import Budget
from finance_agent.contracts.task import TaskContext
from finance_agent.evals.cases import EvalCase
from finance_agent.skills.registry import scan_skill_dir
from finance_agent.skills.resolver import compute_bound_tools, eligible_candidates, resolve_skills
from finance_agent.skills.view import build_skill_view

ALL_TOOL_REFS = [
    ("documents.search", 1), ("documents.read", 1), ("finance.get_metrics", 1),
    ("finance.calculate_growth", 1), ("finance.compare_peers", 1),
]

B_PROMPT_HEADER = "以下是全部可用研究方法(已完整提供,无需读取任何文件):\n\n"


class RecordingRegistry:
    """包装工具注册表:录制每次调用的完整输出(评分依据)。

    只需满足 to_engine_tools 用到的 get()/call() 鸭子类型。
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.outputs: list[dict] = []

    def get(self, name: str):
        return self._inner.get(name)

    def find(self, name: str):
        return self._inner.find(name)

    def list_tools(self):
        return self._inner.list_tools()

    def call(self, name: str, args: dict, ctx: TaskContext):
        result = self._inner.call(name, args, ctx)
        payload = result.payload
        self.outputs.append({
            "tool": name,
            "ok": result.ok,
            "result": payload.model_dump(mode="json") if result.ok and hasattr(payload, "model_dump") else None,
            "error": None if result.ok else result.error.payload(),
        })
        return result


@dataclass
class CaseResult:
    case_id: str
    group: str
    status: str = "not_run"
    result: dict | None = None
    loaded_skills: list[str] = field(default_factory=list)
    tool_outputs: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    wall_seconds: float = 0.0
    error: str | None = None
    notes: str = ""


def _empty_view(workspace: Path) -> Path:
    view_root = workspace / "skills-view"
    if view_root.exists():
        shutil.rmtree(view_root)
    (view_root / "skills").mkdir(parents=True)
    return view_root


def _full_bodies_prompt(skills_dir: Path) -> str:
    bodies = [p.read_text(encoding="utf-8") for p in sorted(skills_dir.glob("*/*/SKILL.md"))]
    return B_PROMPT_HEADER + "\n\n---\n\n".join(bodies)


async def run_case(
    case: EvalCase,
    group: str,
    *,
    model,
    workspace: Path,
    skills_dir: Path,
    user_overrides: dict | None = None,
) -> CaseResult:
    workspace.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    if group == "D":
        from finance_agent.evals.pipeline_d import run_pipeline_d

        res = run_pipeline_d(case)
        res.group = "D"
        res.wall_seconds = time.monotonic() - started
        return res

    registry = RecordingRegistry(build_default_registry())
    budget = Budget(max_model_calls=15, max_tool_calls=30)
    ctx_factory = make_ctx_factory(datetime.fromisoformat(case.as_of), budget.check_tool)

    async with open_sqlite_saver(workspace / "checkpoint.sqlite") as saver:
        if group == "A":
            agent = build_research_agent(
                model, skills_view_root=_empty_view(workspace),
                engine_tools=to_engine_tools(ALL_TOOL_REFS, registry, ctx_factory),
                checkpointer=saver,
            )
        elif group == "B":
            agent = build_research_agent(
                model, skills_view_root=_empty_view(workspace),
                engine_tools=to_engine_tools(ALL_TOOL_REFS, registry, ctx_factory),
                checkpointer=saver, extra_system_prompt=_full_bodies_prompt(skills_dir),
            )
        elif group == "C":
            resolved = resolve_skills(scan_skill_dir(skills_dir), build_default_registry(),
                                      user_overrides=user_overrides)
            candidates = eligible_candidates(resolved)
            view_root = workspace / "skills-view"
            build_skill_view(candidates, view_root)
            refs = compute_bound_tools(candidates, build_default_registry())
            agent = build_research_agent(
                model, skills_view_root=view_root,
                engine_tools=to_engine_tools(refs, registry, ctx_factory),
                checkpointer=saver,
            )
        else:
            msg = f"未知分组: {group}"
            raise ValueError(msg)

        config = run_config(f"eval-{case.case_id}")
        objective_text = (
            f"{case.objective}\n涉及公司: {', '.join(case.entity_ids)}\n"
            f"任务截止时间(as_of): {case.as_of}"
        )
        outcome = await stream_run(agent, {"messages": [("user", objective_text)]}, config, budget)

    return CaseResult(
        case_id=case.case_id, group=group, status=outcome.status,
        result=outcome.result, loaded_skills=outcome.loaded_skills,
        tool_outputs=registry.outputs, budget=outcome.budget,
        usage=outcome.usage, wall_seconds=time.monotonic() - started,
        error=outcome.error,
    )
