"""Deep Agents Agent 装配(M2)。

与 M0 实验版的差异:
- 金融工具来自 M1 ToolRegistry(经绑定集合过滤,§8.2);
- Skill 视图来自 skills.resolver 的候选(M2 注册表驱动,§7.2/§7.3);
- 结构化结果使用 contracts.ResearchResult 完整契约(§11)。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.types import Checkpointer

from finance_agent.contracts.result import ResearchResult

M2_SYSTEM_PROMPT = """\
你是金融研究 Agent。基于标准化财务观测与文档证据完成研究任务。

执行约束:
- 系统提示中列出的 skills 是简介。判断与任务相关时,先用 read_file 读取对应 \
SKILL.md 正文并按其中的方法执行;没有合适的 Skill 就直接用现有工具做研究, \
不强行套用。
- 财务数值只能来自工具返回;增长率用 finance_calculate_growth 计算, \
不自行心算。
- 不得传入晚于任务截止时间的 as_of;省略 as_of 即任务截止时间。
- 工具返回 {"ok": false, "error": ...} 时按 alternatives 调整,不要原样重试。
- 结论中每个数值引用其来源:observation_id(obs-)、calculation_id(calc-)、 \
evidence_id(chk-);查不到的写入 information_gaps,不编造。

完成后调用 ResearchResult 工具提交结构化结果。
"""


def build_research_agent(
    model: BaseChatModel,
    *,
    skills_view_root: Path,
    engine_tools: list[BaseTool],
    checkpointer: Checkpointer | None = None,
    interrupt_on: dict[str, bool] | None = None,
) -> Any:
    permissions = [
        FilesystemPermission(operations=["write"], paths=["/"], mode="deny"),
    ]
    return create_deep_agent(
        model=model,
        tools=engine_tools,
        system_prompt=M2_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=FilesystemBackend(root_dir=skills_view_root),
        permissions=permissions,
        response_format=ToolStrategy(ResearchResult),
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
    )


def make_ctx_factory(task_as_of: datetime, budget_check=None):
    """构造 TaskContext 工厂:as_of 注入 + 预算预检查桥接。"""
    from finance_agent.contracts.task import TaskContext

    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return TaskContext(
            as_of=task_as_of,
            task_id=None,
            budget_check=budget_check,
        )

    return factory
