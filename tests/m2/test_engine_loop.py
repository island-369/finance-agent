"""M2 离线全链路测试:Skill 触发/不选/执行记录/新增 Skill 不改循环。

用 ReactiveScriptedModel 走真实的 deepagents 图执行(与真实模型同一装配),
验证 §17 M2 的四条退出条件。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from finance_agent.adapters.engines.deepagents.agent import (
    build_research_agent,
    make_ctx_factory,
)
from finance_agent.adapters.engines.deepagents.runner import run_config, stream_run
from finance_agent.adapters.engines.deepagents.tools import to_engine_tools
from finance_agent.application.run_service import prepare_run, save_run_record
from finance_agent.bootstrap import build_default_registry
from finance_agent.budget import Budget
from tests.m2.helpers import (
    ReactiveScriptedModel,
    read_skill_msg,
    research_result_msg,
    tool_call_msg,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime.fromisoformat("2026-08-31T23:59:59+08:00")
OBJECTIVE = "分析 demo-company-a 2026 年上半年净利润变化,识别与收入变化不一致的环节"


def script_skill_flow() -> list:
    """读 Skill → 取数 → 计算 → 提交(引用动态 calculation_id)。"""
    return [
        read_skill_msg("earnings-analysis", "c1"),
        tool_call_msg(
            "finance_get_metrics",
            {
                "entity_id": "demo-company-a",
                "metric": "net_profit",
                "basis": "cumulative",
                "period_start": "2025-01-01",
                "period_end": "2026-06-30",
            },
            "c2",
        ),
        tool_call_msg(
            "finance_calculate_growth",
            {
                "current_observation_id": "obs-a-np-cum-2026h1-v2",
                "base_observation_id": "obs-a-np-cum-2025h1",
            },
            "c3",
        ),
        research_result_msg(OBJECTIVE, "demo-company-a"),
    ]


async def run_scripted(script: list, tmp_path: Path, **prepare_kwargs):
    registry = build_default_registry()
    plan = prepare_run(
        objective=OBJECTIVE,
        entity_ids=["demo-company-a"],
        as_of=AS_OF.isoformat(),
        tool_registry=registry,
        runtime_dir=tmp_path,
        **prepare_kwargs,
    )
    budget = Budget()
    ctx_factory = make_ctx_factory(AS_OF, budget.check_tool)
    engine_tools = to_engine_tools(plan.bound_tool_refs, registry, ctx_factory)
    saver = InMemorySaver()
    agent = build_research_agent(
        ReactiveScriptedModel(responses=script),
        skills_view_root=plan.view_root,
        engine_tools=engine_tools,
        checkpointer=saver,
    )
    config = run_config(plan.run_id)
    outcome = await stream_run(agent, {"messages": [("user", OBJECTIVE)]}, config, budget)
    record_path = save_run_record(plan, outcome, {"model": "scripted"}, record_dir=tmp_path / "records" / plan.run_id)
    return plan, outcome, record_path


class TestSkillTriggeredFlow:
    async def test_full_flow_with_skill(self, tmp_path: Path):
        _plan, outcome, record_path = await run_scripted(script_skill_flow(), tmp_path)

        # 退出条件 1:问题触发合适的 Skill(实际 read_file 了正文)
        assert outcome.status == "succeeded"
        assert outcome.loaded_skills == ["earnings-analysis"]

        tool_names = [c["name"] for c in outcome.tool_calls]
        assert "finance_get_metrics" in tool_names
        assert "finance_calculate_growth" in tool_names
        assert outcome.budget["model_calls"] == 4

        # 结果引用了工具生成的 calculation_id
        assert outcome.result["calculation_refs"]
        assert outcome.result["calculation_refs"][0].startswith("calc-")

        # 执行记录完整落盘
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["loaded_skills"] == ["earnings-analysis"]
        assert record["no_skill_selected"] is False
        assert "finance.calculate_growth@1" in record["bound_tools"]
        assert record["result"]["calculation_refs"]
        assert record["skills"]["candidates"] == [
            "announcement-impact@1.0.0",
            "earnings-analysis@1.0.0",
            "peer-comparison@1.0.0",
        ]

    async def test_no_skill_selected_not_forced(self, tmp_path: Path):
        """退出条件 2:不读 Skill 直接研究 → 记录 no_skill_selected,不强行匹配。"""
        script = [
            tool_call_msg(
                "finance_get_metrics",
                {"entity_id": "demo-company-a", "metric": "revenue", "basis": "cumulative"},
                "c1",
            ),
            research_result_msg(OBJECTIVE, "demo-company-a"),
        ]
        _plan, outcome, record_path = await run_scripted(script, tmp_path)
        assert outcome.status == "succeeded"
        assert outcome.loaded_skills == []
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["no_skill_selected"] is True

    async def test_explicit_missing_skill_fails_before_run(self, tmp_path: Path):
        from finance_agent.skills.resolver import SkillResolutionError

        registry = build_default_registry()
        with pytest.raises(SkillResolutionError, match="不存在"):
            prepare_run(
                objective=OBJECTIVE,
                entity_ids=["demo-company-a"],
                as_of=AS_OF.isoformat(),
                tool_registry=registry,
                task_preferences=["no-such-skill"],
                runtime_dir=tmp_path,
            )


class TestNewSkillWithoutLoopChange:
    async def test_new_skill_discovered_automatically(self, tmp_path: Path):
        """退出条件 4:新增合格 Skill 只需放入目录,解析与执行代码零修改。"""
        skills_dir = tmp_path / "skills"
        for name, ver, required in [
            ("earnings-analysis", "1.0.0", ["finance.get_metrics@1", "finance.calculate_growth@1"]),
            ("announcement-impact", "1.0.0", ["documents.search@1", "documents.read@1", "finance.get_metrics@1"]),
            ("peer-comparison", "1.0.0", ["finance.compare_peers@1", "finance.get_metrics@1"]),
            ("quick-ratio-check", "0.1.0", ["finance.get_metrics@1"]),  # 新增
        ]:
            d = skills_dir / name / ver
            d.mkdir(parents=True)
            req = "\n".join(f"    - {r}" for r in required)
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: 测试用 {name}\nmetadata:\n"
                f'  app_version: "{ver}"\n  app_required_tools:\n{req}\n---\n\n# {name}\n',
                encoding="utf-8",
            )

        _plan, outcome, record_path = await run_scripted(
            script_skill_flow(), tmp_path / "rt", skills_dir=skills_dir
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert "quick-ratio-check@0.1.0" in record["skills"]["candidates"]
        assert outcome.status == "succeeded"  # 执行循环未被修改,行为不变

    async def test_bound_tools_follow_candidates(self, tmp_path: Path):
        """绑定集合随候选变化:只要 peer-comparison 时,calculate_growth 不绑定。"""
        registry = build_default_registry()
        plan = prepare_run(
            objective="比较同业收入",
            entity_ids=["demo-company-a", "demo-company-b"],
            as_of=AS_OF.isoformat(),
            tool_registry=registry,
            task_preferences=["peer-comparison"],
            runtime_dir=tmp_path,
        )
        refs = [f"{n}@{m}" for n, m in plan.bound_tool_refs]
        assert "finance.compare_peers@1" in refs
        assert "finance.get_metrics@1" in refs
        assert "finance.calculate_growth@1" not in refs
