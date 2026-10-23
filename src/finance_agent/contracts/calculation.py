"""计算结果契约(设计 §8.3)。

计算由代码完成并记录:公式、公式版本、输入观测 ID、参数;模型不得重新
生成公式结果。不可计算(零分母、缺失输入、口径不可比)时 value 为 None
并给出机器可读原因,不抛异常。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

NonComputableReason = Literal[
    "ZERO_DENOMINATOR",      # 基数为零
    "MISSING_INPUT",         # 输入观测存在但数值缺失
    "INCOMPARABLE_INPUTS",   # 口径/币种/期间不可比
]


class CalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    calculation_id: str
    formula: str
    formula_version: str
    input_observation_ids: list[str]
    value: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    non_computable_reason: NonComputableReason | None = None
    issues: list[str] = Field(default_factory=list, description="不可比时的具体差异项")
    caveats: list[str] = Field(default_factory=list, description="可计算但需解释的限制,如负基数")

    @field_serializer("value")
    def _ser_value(self, v: Decimal | None) -> str | None:
        return str(v) if v is not None else None
