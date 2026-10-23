"""任务与执行上下文契约。

TaskRequest 对应设计 §13.2 的任务请求(结构对齐,首版不开放全部字段)。
TaskContext 是工具执行端可见的上下文:任务 as_of 在这里注入,工具据此
校验模型传入的时间参数,不允许扩大截止时间。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field


class BudgetSpec(BaseModel):
    max_model_calls: int = Field(default=15, ge=1)
    max_tool_calls: int = Field(default=30, ge=1)
    max_wall_clock_seconds: int = Field(default=600, ge=1)
    result_repair_rounds: int = Field(default=2, ge=0)


class TaskRequest(BaseModel):
    objective: str = Field(min_length=1)
    entity_ids: list[str] = Field(min_length=1)
    as_of: datetime
    skill_preferences: list[str] = Field(default_factory=list)
    profile_id: str | None = None
    output_schema: str = Field(default="research-result.v1")
    budget: BudgetSpec = Field(default_factory=BudgetSpec)


@dataclass
class TaskContext:
    """工具处理函数的执行上下文;秘钥不进入本结构。"""

    as_of: datetime
    task_id: str | None = None
    budget_check: Callable[[], bool] | None = field(default=None)
    """返回 False 表示剩余额度不足,工具应返回 BUDGET_EXCEEDED。"""
