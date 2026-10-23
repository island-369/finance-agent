"""工具规格契约(设计 §8.1 ToolSpec)。

每个工具登记:名称、主版本、输入/输出模型(同时提供 JSON Schema)、超时、
重试策略、只读属性、幂等特性、处理函数。调用由注册中心按 schema 校验,
不只依赖模型遵循工具描述。处理函数是纯 Python 签名,不依赖任何模型消息对象。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from finance_agent.contracts.task import TaskContext


@dataclass(frozen=True)
class ToolSpec:
    name: str
    """稳定名称,如 finance.get_metrics;供应商字段差异由数据适配器转换。"""

    major_version: int
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel] | None
    timeout_seconds: float
    retry_policy: str  # "none" | "limited_backoff"
    read_only: bool
    idempotent: bool
    handler: Callable[[BaseModel, TaskContext], Any]

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.major_version}"

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "major_version": self.major_version,
            "ref": self.ref,
            "description": self.description,
            "read_only": self.read_only,
            "idempotent": self.idempotent,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy,
            "input_schema": self.input_schema(),
        }
