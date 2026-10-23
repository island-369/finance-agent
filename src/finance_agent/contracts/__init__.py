"""核心契约:任务、观测、证据、计算、结果与工具类型。

本包(及 finance / tools / retrieval / ports)不得导入 deepagents / langchain /
langgraph;框架导入只允许出现在 adapters 与装配处(设计 §5)。
时间内部统一 UTC(datetime 带 tzinfo);界面层负责 Asia/Shanghai 展示转换。
"""

from finance_agent.contracts.calculation import CalculationResult
from finance_agent.contracts.common import (
    BUDGET_EXCEEDED,
    DATA_NOT_FOUND,
    INCOMPARABLE_METRICS,
    INVALID_ARGUMENT,
    PROVIDER_ERROR,
    RATE_LIMITED,
    TIMEOUT,
    ToolError,
    ToolResult,
    is_retriable,
)
from finance_agent.contracts.evidence import Chunk, DocumentVersion, EvidenceRef
from finance_agent.contracts.observation import MetricObservation
from finance_agent.contracts.result import ResearchResult
from finance_agent.contracts.task import BudgetSpec, TaskContext, TaskRequest
from finance_agent.contracts.toolspec import ToolSpec

__all__ = [
    "BUDGET_EXCEEDED",
    "DATA_NOT_FOUND",
    "INCOMPARABLE_METRICS",
    "INVALID_ARGUMENT",
    "PROVIDER_ERROR",
    "RATE_LIMITED",
    "TIMEOUT",
    "BudgetSpec",
    "CalculationResult",
    "Chunk",
    "DocumentVersion",
    "EvidenceRef",
    "MetricObservation",
    "ResearchResult",
    "TaskContext",
    "TaskRequest",
    "ToolError",
    "ToolResult",
    "ToolSpec",
    "is_retriable",
]
