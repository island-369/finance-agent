"""确定性金融计算:同比/环比增长率(设计 §8.3)。

规则(全部有测试覆盖):
- 公式 (本期 - 同期) / 同期;结果记录输入 ID、公式与公式版本。
- 分母为零:返回 value=None + non_computable_reason=ZERO_DENOMINATOR,不抛异常。
- 输入缺失(观测存在但 value=None):MISSING_INPUT。
- 口径不可比(指标/基准/合并口径/币种/单位/期间形状任一不同):
  INCOMPARABLE_INPUTS + 差异项列表。
- 基数为负:保留计算值,并附加 NEGATIVE_BASE 解释限制。
- 精度:除法结果 quantize 到 8 位小数,金额 Decimal 全程不经过 float。
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from finance_agent.contracts.calculation import CalculationResult
from finance_agent.contracts.observation import MetricObservation
from finance_agent.finance.comparability import comparability_issues

GROWTH_FORMULA = "(current - base) / base"
GROWTH_FORMULA_VERSION = "growth.yoy@1"
_QUANT = Decimal("0.00000001")


def _calc_id() -> str:
    return f"calc-{uuid.uuid4().hex[:10]}"


def calculate_growth(current: MetricObservation, base: MetricObservation) -> CalculationResult:
    issues = comparability_issues(current, base)
    if issues:
        return CalculationResult(
            calculation_id=_calc_id(),
            formula=GROWTH_FORMULA,
            formula_version=GROWTH_FORMULA_VERSION,
            input_observation_ids=[current.observation_id, base.observation_id],
            non_computable_reason="INCOMPARABLE_INPUTS",
            issues=issues,
        )

    if current.value is None or base.value is None:
        missing = [
            obs.observation_id
            for obs in (current, base)
            if obs.value is None
        ]
        return CalculationResult(
            calculation_id=_calc_id(),
            formula=GROWTH_FORMULA,
            formula_version=GROWTH_FORMULA_VERSION,
            input_observation_ids=[current.observation_id, base.observation_id],
            non_computable_reason="MISSING_INPUT",
            issues=[f"数值缺失: {oid}" for oid in missing],
        )

    if base.value == 0:
        return CalculationResult(
            calculation_id=_calc_id(),
            formula=GROWTH_FORMULA,
            formula_version=GROWTH_FORMULA_VERSION,
            input_observation_ids=[current.observation_id, base.observation_id],
            non_computable_reason="ZERO_DENOMINATOR",
            issues=[f"基数为零: {base.observation_id} = 0"],
        )

    value = ((current.value - base.value) / base.value).quantize(_QUANT, rounding=ROUND_HALF_UP)
    caveats: list[str] = []
    if base.value < 0:
        caveats.append(
            f"NEGATIVE_BASE: 基数为负({base.value}),增长率符号只表示相对负基数的"
            "变化方向,不代表常规意义下的增长/下降,解释时需说明基数符号。"
        )

    return CalculationResult(
        calculation_id=_calc_id(),
        formula=GROWTH_FORMULA,
        formula_version=GROWTH_FORMULA_VERSION,
        input_observation_ids=[current.observation_id, base.observation_id],
        value=value,
        unit="ratio",
        currency=None,
        caveats=caveats,
    )
