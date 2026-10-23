"""M1 工具注册表 → Deep Agents 工具。

名称映射:核心工具名 finance.get_metrics(点号)在 OpenAI 兼容工具名中
不合法(仅 [a-zA-Z0-9_-]),引擎侧转为下划线(finance_get_metrics);
路由经闭包回到原 spec,模型无感知(设计 §8.2:工具名在核心稳定,
供应商差异在适配器转换)。

返回统一 JSON:成功 {"ok": true, "result": {...}};
失败 {"ok": false, "error": {code/message/retriable/detail/alternatives}},
模型可据 alternatives 调整策略(§8.5)。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from finance_agent.contracts.task import TaskContext
from finance_agent.contracts.toolspec import ToolSpec
from finance_agent.tools.registry import ToolRegistry


def engine_tool_name(core_name: str) -> str:
    return core_name.replace(".", "_")


def core_tool_name(engine_name: str) -> str:
    """下划线名还原为核心名(仅用于展示/记录;实际路由不经过这里)。"""
    mapping = {
        "documents_search": "documents.search",
        "documents_read": "documents.read",
        "finance_get_metrics": "finance.get_metrics",
        "finance_calculate_growth": "finance.calculate_growth",
        "finance_compare_peers": "finance.compare_peers",
    }
    return mapping.get(engine_name, engine_name)


def to_engine_tool(
    spec: ToolSpec,
    tool_registry: ToolRegistry,
    ctx_factory: Callable[[], TaskContext],
) -> BaseTool:
    def _run(**kwargs: Any) -> str:
        result = tool_registry.call(spec.name, kwargs, ctx_factory())
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    return StructuredTool(
        name=engine_tool_name(spec.name),
        description=spec.description,
        args_schema=spec.input_model,
        func=_run,
    )


def to_engine_tools(
    refs: list[tuple[str, int]],
    tool_registry: ToolRegistry,
    ctx_factory: Callable[[], TaskContext],
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for name, _major in refs:
        tools.append(to_engine_tool(tool_registry.get(name), tool_registry, ctx_factory))
    return tools
