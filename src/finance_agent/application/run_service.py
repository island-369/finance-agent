"""M2 任务准备:解析 Skill → 依赖检查 → 绑定工具 → 只读视图 → 执行计划。

对应设计 §6.2 步骤 1–4 的雏形(M3 引入任务表与状态机)。
执行计划即任务快照(§7.3):候选、排除原因、绑定工具与 manifest
全部写入执行记录,执行中新增发现不改变本次解析结果。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from finance_agent.skills.registry import scan_skill_dir
from finance_agent.skills.resolver import (
    ResolvedSkill,
    compute_bound_tools,
    eligible_candidates,
    resolve_skills,
)
from finance_agent.skills.view import build_skill_view
from finance_agent.tools.registry import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class RunPlan:
    run_id: str
    created_at: str
    objective: str
    entity_ids: list[str]
    as_of: str
    resolved: list[ResolvedSkill]
    candidates: list[ResolvedSkill]
    bound_tool_refs: list[tuple[str, int]]
    view_root: Path
    manifest: list[dict]

    @property
    def no_candidates(self) -> bool:
        return not self.candidates

    def snapshot(self) -> dict:
        """执行记录的任务快照部分。"""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "objective": self.objective,
            "entity_ids": self.entity_ids,
            "as_of": self.as_of,
            "engine": {"name": "deepagents", "adapter": "m2"},
            "skills": {
                "resolved": [
                    {
                        "ref": r.ref,
                        "available": r.available,
                        "reason": r.reason,
                        "degraded_tools": list(r.degraded_tools),
                    }
                    for r in self.resolved
                ],
                "candidates": [r.ref for r in self.candidates],
                "no_candidates": self.no_candidates,
            },
            "bound_tools": [f"{n}@{m}" for n, m in self.bound_tool_refs],
            "manifest": self.manifest,
        }


def load_user_overrides(path: Path | None) -> dict[str, str]:
    """用户已发布覆盖(name → version);文件不存在视为无覆盖。"""
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"用户覆盖文件必须是 name→version 映射: {path}")
    return {str(k): str(v) for k, v in data.items()}


def prepare_run(
    *,
    objective: str,
    entity_ids: list[str],
    as_of: str,
    tool_registry: ToolRegistry,
    skills_dir: Path | None = None,
    user_overrides: dict[str, str] | None = None,
    task_preferences: list[str] | None = None,
    runtime_dir: Path | None = None,
) -> RunPlan:
    """解析任务并物化只读视图;显式指定无法满足时抛 SkillResolutionError。"""
    skills_dir = skills_dir or (PROJECT_ROOT / "skills")
    runtime_dir = runtime_dir or (PROJECT_ROOT / "data" / "runtime")
    records = scan_skill_dir(skills_dir)
    resolved = resolve_skills(
        records, tool_registry, user_overrides=user_overrides, task_preferences=task_preferences
    )
    # 显式指定 Skill 即任务边界:候选收敛为指定集合,其余仅记录解析结果
    pref_names = {p.partition("@")[0] for p in (task_preferences or [])} or None
    candidates = eligible_candidates(resolved, only=pref_names)
    bound_refs = compute_bound_tools(candidates, tool_registry)

    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    view_root = runtime_dir / "m2-runs" / run_id / "skills-view"
    manifest = build_skill_view(candidates, view_root)

    return RunPlan(
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        objective=objective,
        entity_ids=entity_ids,
        as_of=as_of,
        resolved=resolved,
        candidates=candidates,
        bound_tool_refs=bound_refs,
        view_root=view_root,
        manifest=manifest,
    )


def save_run_record(plan: RunPlan, outcome, model_desc: dict, record_dir: Path | None = None) -> Path:
    record_dir = record_dir or (plan.view_root.parent)
    record_dir.mkdir(parents=True, exist_ok=True)
    record = {
        **plan.snapshot(),
        "model": model_desc,
        "loaded_skills": outcome.loaded_skills,
        "no_skill_selected": not outcome.loaded_skills,
        "status": outcome.status,
        "error": outcome.error,
        "quality_flags": outcome.quality_flags,
        "budget": outcome.budget,
        "usage": outcome.usage,
        "tool_calls": outcome.tool_calls,
        "result": outcome.result,
        "events": outcome.events,
    }
    path = record_dir / "record.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
