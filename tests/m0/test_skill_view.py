"""M0 离线回归测试。

覆盖与 `uv run m0 check` 相同的能力项,使用确定性脚本模型与临时目录,
不需要模型秘钥。真实模型调用验证见 docs/M0-能力矩阵与选型记录.md。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from finance_agent.m0.agent import build_agent
from finance_agent.m0.budget import Budget
from finance_agent.m0.checkpoints import open_sqlite_saver
from finance_agent.m0.fixtures import DEFAULT_OBSERVATIONS
from finance_agent.m0.runner import resume_payload, stream_run
from finance_agent.m0.skills_view import build_skill_view
from finance_agent.m0.testing import ScriptedChatModel
from finance_agent.m0.tools import (
    BUDGET_EXCEEDED,
    TIME_BOUNDARY_VIOLATION,
    make_finance_get_metrics_tool,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_AS_OF = datetime.fromisoformat("2026-08-31T23:59:59+08:00")
OBJECTIVE = "分析 demo-company-a 2026 年上半年净利润变化,识别与收入变化不一致的环节并给出证据"

FINAL_ARGS = {
    "objective": "分析 demo-company-a 2026 年上半年净利润变化",
    "summary": "2026H1 净利润(修订口径)2.72 亿元;Q2 利润率环比下滑。",
    "key_findings": [
        "2026Q1 净利润 98,000,000 元(修订版 v2,obs-013)",
        "2026Q2 净利润 174,000,000 元(obs-012),单季利润率 6.0%,低于 Q1 的 7.0%",
    ],
    "metric_refs": ["obs-013", "obs-012"],
    "evidence_refs": ["/skills/earnings-analysis/SKILL.md"],
    "assumptions": [],
    "information_gaps": ["缺少成本科目明细,无法定位利润率下滑的具体科目"],
}


def scripted_messages() -> list[AIMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "finance_get_metrics", "args": {"entity_id": "demo-company-a", "metric": "net_profit"}, "id": "c1", "type": "tool_call"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "args": {"file_path": "/skills/earnings-analysis/SKILL.md"}, "id": "c2", "type": "tool_call"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "M0ResearchResult", "args": FINAL_ARGS, "id": "c3", "type": "tool_call"}],
        ),
    ]


def scripted_model(messages: list[AIMessage], i: int = 0) -> ScriptedChatModel:
    m = ScriptedChatModel(responses=messages)
    m.i = i
    return m


@pytest.fixture()
def skills_view(tmp_path: Path) -> Path:
    build_skill_view(PROJECT_ROOT / "skills", tmp_path / "skills-view")
    return tmp_path / "skills-view"


class TestSkillView:
    def test_builds_flat_view_with_manifest(self, tmp_path: Path):
        # M2 起 skills/ 含多个包;M0 视图逻辑应取每包最新版本
        manifest = build_skill_view(PROJECT_ROOT / "skills", tmp_path / "view")
        by_name = {m["name"]: m for m in manifest}
        assert by_name["earnings-analysis"]["version"] == "1.0.0"
        assert len(by_name["earnings-analysis"]["skill_md_sha256"]) == 64
        assert (tmp_path / "view" / "skills" / "earnings-analysis" / "SKILL.md").is_file()
        assert (tmp_path / "view" / "manifest.json").is_file()

    def test_picks_latest_version(self, tmp_path: Path):
        repo = tmp_path / "skills" / "demo"
        for ver in ("0.1.0", "0.2.0", "0.10.0"):
            d = repo / ver
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nname: demo\ndescription: v{ver}\n---\n\n# {ver}", encoding="utf-8"
            )
        manifest = build_skill_view(tmp_path / "skills", tmp_path / "view")
        assert manifest[0]["version"] == "0.10.0"


class TestFinanceTool:
    def test_as_of_later_than_task_rejected(self):
        tool = make_finance_get_metrics_tool(DEFAULT_OBSERVATIONS, Budget(), TASK_AS_OF)
        out = json.loads(
            tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit", "as_of": "2026-12-31T00:00:00+08:00"})
        )
        assert out["error"]["code"] == TIME_BOUNDARY_VIOLATION

    def test_revision_selected_by_as_of(self):
        tool = make_finance_get_metrics_tool(DEFAULT_OBSERVATIONS, Budget(), TASK_AS_OF)
        before = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit", "as_of": "2026-05-01T00:00:00+08:00"}))
        q1_before = next(o for o in before["observations"] if o["period_end"] == "2026-03-31")
        assert (q1_before["revision_id"], q1_before["value"]) == ("v1", "112000000.00")

        after = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit"}))
        q1_after = next(o for o in after["observations"] if o["period_end"] == "2026-03-31")
        assert (q1_after["revision_id"], q1_after["value"]) == ("v2", "98000000.00")

    def test_budget_exhausted_returns_structured_error(self):
        tool = make_finance_get_metrics_tool(DEFAULT_OBSERVATIONS, Budget(max_tool_calls=0), TASK_AS_OF)
        out = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "revenue"}))
        assert out["error"]["code"] == BUDGET_EXCEEDED

    def test_data_not_found_lists_alternatives(self):
        tool = make_finance_get_metrics_tool(DEFAULT_OBSERVATIONS, Budget(), TASK_AS_OF)
        out = json.loads(tool.invoke({"entity_id": "no-such-co", "metric": "revenue"}))
        assert out["error"]["code"] == "DATA_NOT_FOUND"
        assert "demo-company-a" in out["error"]["available_entities"]


class TestEndToEnd:
    async def test_scripted_run_full_pipeline(self, skills_view: Path, tmp_path: Path):
        budget = Budget(max_model_calls=6, max_tool_calls=6)
        async with open_sqlite_saver(tmp_path / "e2e.sqlite") as saver:
            agent = build_agent(
                scripted_model(scripted_messages()),
                skills_view_root=skills_view,
                budget=budget,
                task_as_of=TASK_AS_OF,
                checkpointer=saver,
            )
            config = {"configurable": {"thread_id": "e2e"}}
            outcome = await stream_run(agent, {"messages": [("user", OBJECTIVE)]}, config, budget)

        assert outcome.status == "succeeded"
        assert outcome.result == FINAL_ARGS
        tool_names = [e["name"] for e in outcome.events if e["type"] == "tool_start"]
        assert "finance_get_metrics" in tool_names
        assert "read_file" in tool_names  # Skill 正文按需加载
        assert (budget.model_calls, budget.tool_calls) == (3, 2)

    async def test_budget_abort_on_model_calls(self, skills_view: Path, tmp_path: Path):
        budget = Budget(max_model_calls=2, max_tool_calls=6)
        async with open_sqlite_saver(tmp_path / "budget.sqlite") as saver:
            agent = build_agent(
                scripted_model(scripted_messages()),
                skills_view_root=skills_view,
                budget=budget,
                task_as_of=TASK_AS_OF,
                checkpointer=saver,
            )
            outcome = await stream_run(
                agent, {"messages": [("user", OBJECTIVE)]},
                {"configurable": {"thread_id": "budget"}}, budget,
            )
        assert outcome.status == "budget_exceeded"
        assert budget.model_calls == 2  # 越界调用如实计数


class TestInterruptResume:
    async def test_interrupt_then_resume_across_connections(self, skills_view: Path, tmp_path: Path):
        db = tmp_path / "hitl.sqlite"
        script = scripted_messages()
        budget = Budget(max_model_calls=6, max_tool_calls=6)
        config = {"configurable": {"thread_id": "hitl"}}
        interrupt_on = {"finance_get_metrics": True}

        async with open_sqlite_saver(db) as saver:
            agent1 = build_agent(
                scripted_model(script, 0), skills_view_root=skills_view, budget=budget,
                task_as_of=TASK_AS_OF, checkpointer=saver, interrupt_on=interrupt_on,
            )
            out1 = await stream_run(agent1, {"messages": [("user", OBJECTIVE)]}, config, budget)
        assert out1.status == "waiting_approval"
        assert out1.result is None
        assert budget.tool_calls == 0  # 中断发生在工具执行前

        async with open_sqlite_saver(db) as saver:
            agent2 = build_agent(
                scripted_model(script, 1), skills_view_root=skills_view, budget=budget,
                task_as_of=TASK_AS_OF, checkpointer=saver, interrupt_on=interrupt_on,
            )
            out2 = await stream_run(agent2, Command(resume=resume_payload(approve=True)), config, budget)
        assert out2.status == "succeeded"
        assert out2.result == FINAL_ARGS
        assert (budget.model_calls, budget.tool_calls) == (3, 2)

    async def test_parallel_tool_calls_need_matching_decisions(
        self, skills_view: Path, tmp_path: Path
    ):
        """真实模型一回合发起多个受审批门控的调用时,决定数量必须匹配(回归)。"""
        from finance_agent.m0.runner import build_resume_payload

        db = tmp_path / "hitl-parallel.sqlite"
        budget = Budget(max_model_calls=6, max_tool_calls=6)
        config = {"configurable": {"thread_id": "hitl-parallel"}}
        interrupt_on = {"finance_get_metrics": True}

        # 第一回合并行两个 finance_get_metrics 调用,均被审批门挂起
        parallel_script = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "finance_get_metrics", "args": {"entity_id": "demo-company-a", "metric": "net_profit"}, "id": "p1", "type": "tool_call"},
                    {"name": "finance_get_metrics", "args": {"entity_id": "demo-company-a", "metric": "revenue"}, "id": "p2", "type": "tool_call"},
                ],
            ),
            *scripted_messages()[1:],  # read_file 与最终结构化结果
        ]
        async with open_sqlite_saver(db) as saver:
            agent1 = build_agent(
                scripted_model(parallel_script, 0), skills_view_root=skills_view,
                budget=budget, task_as_of=TASK_AS_OF, checkpointer=saver,
                interrupt_on=interrupt_on,
            )
            out1 = await stream_run(agent1, {"messages": [("user", OBJECTIVE)]}, config, budget)
        assert out1.status == "waiting_approval"

        async with open_sqlite_saver(db) as saver:
            agent2 = build_agent(
                scripted_model(parallel_script, 1), skills_view_root=skills_view,
                budget=budget, task_as_of=TASK_AS_OF, checkpointer=saver,
                interrupt_on=interrupt_on,
            )
            payload = await build_resume_payload(agent2, config, approve=True)
            assert len(payload["decisions"]) == 2
            out2 = await stream_run(agent2, Command(resume=payload), config, budget)
        assert out2.status == "succeeded"
        assert out2.result == FINAL_ARGS
        assert (budget.model_calls, budget.tool_calls) == (3, 3)
