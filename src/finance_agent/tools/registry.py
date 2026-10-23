"""工具注册中心(设计 §8.1、§8.5)。

调用流程:解析名称 → schema 校验参数 → 预算预检查 → 处理函数 →
统一 ToolResult。ToolError 转为结构化错误负载;意外异常归为
PROVIDER_ERROR(retriable),不把堆栈暴露给模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from finance_agent.contracts.common import (
    BUDGET_EXCEEDED,
    INVALID_ARGUMENT,
    PROVIDER_ERROR,
    ToolError,
    ToolResult,
)
from finance_agent.contracts.task import TaskContext
from finance_agent.contracts.toolspec import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"工具重复注册: {spec.name}")
        self._specs[spec.name] = spec

    def register_all(self, specs: list[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolError(
                INVALID_ARGUMENT,
                f"未知工具: {name}",
                alternatives=[f"可用工具: {', '.join(sorted(self._specs))}"],
            )
        return spec

    def find(self, name: str) -> ToolSpec | None:
        """查询工具;不存在返回 None(供依赖检查等非调用场景使用)。"""
        return self._specs.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def call(self, name: str, args: dict[str, Any], ctx: TaskContext) -> ToolResult:
        try:
            spec = self.get(name)
        except ToolError as e:
            return ToolResult(name, 0, error=e)

        try:
            validated: BaseModel = spec.input_model.model_validate(args)
        except ValidationError as e:
            err = ToolError(
                INVALID_ARGUMENT,
                f"{spec.ref} 参数校验失败",
                detail={"errors": e.errors(include_url=False)},
            )
            return ToolResult(spec.name, spec.major_version, error=err)

        if ctx.budget_check is not None and not ctx.budget_check():
            return ToolResult(
                spec.name,
                spec.major_version,
                error=ToolError(
                    BUDGET_EXCEEDED,
                    f"工具调用预算已用尽({spec.ref})",
                    alternatives=["基于已获得的数据给出部分结论,并说明信息缺口。"],
                ),
            )

        try:
            payload = spec.handler(validated, ctx)
            return ToolResult(spec.name, spec.major_version, payload=payload)
        except ToolError as e:
            return ToolResult(spec.name, spec.major_version, error=e)
        except Exception as e:  # noqa: BLE001 — 意外异常也不外泄堆栈
            return ToolResult(
                spec.name,
                spec.major_version,
                error=ToolError(
                    PROVIDER_ERROR,
                    f"{spec.ref} 执行出现未预期错误: {type(e).__name__}",
                    detail={"exception": str(e)[:200]},
                ),
            )
