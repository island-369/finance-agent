"""结构化错误与工具返回(设计 §8.5)。

统一错误码:INVALID_ARGUMENT / DATA_NOT_FOUND / INCOMPARABLE_METRICS /
TIMEOUT / RATE_LIMITED / PROVIDER_ERROR / BUDGET_EXCEEDED。
错误负载带:是否可重试、机器可读 detail、可行替代动作。参数错误与数据
缺失不盲目重试;查询超时/限流/供应商错误可有限退避重试。
"""

from __future__ import annotations

from typing import Any

INVALID_ARGUMENT = "INVALID_ARGUMENT"
DATA_NOT_FOUND = "DATA_NOT_FOUND"
INCOMPARABLE_METRICS = "INCOMPARABLE_METRICS"
TIMEOUT = "TIMEOUT"
RATE_LIMITED = "RATE_LIMITED"
PROVIDER_ERROR = "PROVIDER_ERROR"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

# 默认可重试的错误码;ToolError 可按场景覆盖(如配置了明确不可重试)
_RETRIABLE_CODES = frozenset({TIMEOUT, RATE_LIMITED, PROVIDER_ERROR})


def is_retriable(code: str, override: bool | None = None) -> bool:
    if override is not None:
        return override
    return code in _RETRIABLE_CODES


class ToolError(Exception):
    """工具执行的结构化错误。注册中心捕获后转为错误负载,不中断调用方。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retriable: bool | None = None,
        detail: dict[str, Any] | None = None,
        alternatives: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = is_retriable(code, retriable)
        self.detail = detail or {}
        self.alternatives = alternatives or []

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "detail": self.detail,
            "alternatives": self.alternatives,
        }


class ToolResult:
    """一次工具调用的统一返回:成功负载或结构化错误,二选一。"""

    def __init__(self, tool: str, tool_version: int, *, payload: Any = None, error: ToolError | None = None) -> None:
        if error is not None and payload is not None:
            raise ValueError("ToolResult 的 payload 与 error 互斥")
        self.tool = tool
        self.tool_version = tool_version
        self.payload = payload
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        base = {"tool": self.tool, "tool_version": self.tool_version, "ok": self.ok}
        if self.error is not None:
            return {**base, "error": self.error.payload()}
        dump = getattr(self.payload, "model_dump", None)
        return {**base, "result": dump(mode="json") if dump else self.payload}
