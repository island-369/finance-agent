"""观测可比性校验(设计 §8.3)。

比较前先校验口径;不一致时返回差异项,由调用方决定以错误还是
"不可计算原因"呈现,不允许默认相加或比较。
"""

from __future__ import annotations

from finance_agent.contracts.observation import MetricObservation


def _period_shape(obs: MetricObservation) -> tuple[int, int, int]:
    """期间形状:(跨月数, 起日, 止日)。同比比较要求形状一致。"""
    months = (obs.period_end.year - obs.period_start.year) * 12 + (
        obs.period_end.month - obs.period_start.month
    )
    return (months, obs.period_start.day, obs.period_end.day)


def comparability_issues(current: MetricObservation, base: MetricObservation) -> list[str]:
    issues: list[str] = []
    if current.metric != base.metric:
        issues.append(f"指标不同: {current.metric} vs {base.metric}")
    if current.basis != base.basis:
        issues.append(f"期间基准不同: {current.basis} vs {base.basis}")
    if current.scope != base.scope:
        issues.append(f"报表口径不同: {current.scope} vs {base.scope}")
    if current.currency != base.currency:
        issues.append(f"币种不同: {current.currency} vs {base.currency}")
    if current.unit != base.unit:
        issues.append(f"单位不同: {current.unit} vs {base.unit}")
    if _period_shape(current) != _period_shape(base):
        issues.append(
            f"期间长度不同: {current.period_label()} vs {base.period_label()}"
        )
    return issues
