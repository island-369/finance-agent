"""标准财务观测契约(设计 §8.3)。

- 金额用 Decimal;零与缺失分开表达:0 表示"披露为零",None 表示缺失/未披露。
- 单季与累计(basis)、合并与母公司(scope)、币种与单位都必须显式;比较前先校验口径。
- available_at 是"该版本可公开获知的时间";修订选择以它为准,不是 retrieved_at。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

Basis = Literal["cumulative", "single_quarter"]
SCOPE_CONSOLIDATED = "合并报表"
SCOPE_PARENT = "母公司报表"


class MetricObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    entity_id: str
    metric: str
    value: Decimal | None = Field(description="Decimal;None 表示缺失/未披露,与 0 区分")
    unit: str = Field(description="计量单位,如 元")
    currency: str | None = Field(description="ISO 币种代码;比率类指标为 None")
    basis: Basis = Field(description="累计(cumulative)或单季(single_quarter)")
    period_start: date
    period_end: date
    scope: str = Field(description="报表口径:合并报表 / 母公司报表 等")
    available_at: datetime = Field(description="该版本可公开获知的时间(UTC)")
    retrieved_at: datetime = Field(description="本系统抓取/导入时间(UTC)")
    source_id: str
    revision_id: str
    note: str | None = Field(default=None, description="缺失原因、修订说明等")

    @field_serializer("value")
    def _ser_value(self, v: Decimal | None) -> str | None:
        # JSON 边界上 Decimal → str,保留精度;进程内仍是 Decimal
        return str(v) if v is not None else None

    def period_label(self) -> str:
        return f"{self.period_start.isoformat()}~{self.period_end.isoformat()}"
