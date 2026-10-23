"""M0 Agent 装配:把模型、Skill 视图、金融工具、检查点组装成 Deep Agent。

对应设计 §4.1 中"应用准备 Skill 快照和工具集合,通过适配器交给引擎"。
框架导入(deepagents/langchain)只出现在 m0 包内,后续 contracts 等核心模块
不得引用它们(§5)。
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

from finance_agent.m0.budget import Budget
from finance_agent.m0.fixtures import DEFAULT_OBSERVATIONS
from finance_agent.m0.result import M0ResearchResult
from finance_agent.m0.tools import make_finance_get_metrics_tool

M0_SYSTEM_PROMPT = """\
你是金融研究 Agent(M0 实验版)。任务:基于标准化财务观测回答研究问题。

执行约束:
- 系统提示中列出的 skills 只是简介;认为相关时先用 read_file 读取对应 SKILL.md \
正文,再按其中的研究方法执行。
- 财务数据只能来自 finance_get_metrics 工具,不得凭记忆填写数值。
- 不得传入晚于任务截止时间的 as_of;省略 as_of 即使用任务截止时间。
- 结论中的每个数值都必须引用其来源观测的 observation_id;查不到的数据写入 \
information_gaps,不要编造。
- 数据为合成样本,结论措辞不需要提示这一点,工具返回中已注明。

完成后调用 M0ResearchResult 工具提交结构化结果。
"""


def build_agent(
    model: BaseChatModel,
    *,
    skills_view_root: Path,
    budget: Budget,
    task_as_of: datetime,
    checkpointer: Checkpointer | None = None,
    observations: list[dict] | None = None,
    response_model: type[M0ResearchResult] = M0ResearchResult,
    interrupt_on: dict[str, bool] | None = None,
) -> Any:
    finance_tool = make_finance_get_metrics_tool(
        observations or DEFAULT_OBSERVATIONS, budget, task_as_of
    )
    tools: list[BaseTool] = [finance_tool]

    # Skill 视图只读:拒绝一切写入/编辑,目录逃逸由 FilesystemBackend 拦截
    permissions = [
        FilesystemPermission(operations=["write"], paths=["/"], mode="deny"),
    ]

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=M0_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=FilesystemBackend(root_dir=skills_view_root),
        permissions=permissions,
        # 显式 ToolStrategy:结构化结果通过工具调用提交,离线假模型与真实模型路径一致
        response_format=ToolStrategy(response_model),
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
    )
