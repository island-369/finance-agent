"""指标口径登记。

指标不只是名字:单位族与币种要求在这里登记,工具用登记表校验输入,
防止"收入/增长率"这类异质指标被静默比较。新增指标 = 在此登记,不改工具。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    label: str
    unit: str
    requires_currency: bool
    description: str


_METRICS: dict[str, MetricDefinition] = {
    m.name: m
    for m in [
        MetricDefinition("revenue", "营业收入", "元", True, "利润表口径的营业收入"),
        MetricDefinition("net_profit", "净利润", "元", True, "归属于母公司股东的净利润"),
        MetricDefinition("gross_profit", "毛利润", "元", True, "营业收入减营业成本"),
        MetricDefinition("net_margin", "净利率", "%", False, "净利润 / 营业收入,比率类"),
    ]
}


def get_metric(name: str) -> MetricDefinition | None:
    return _METRICS.get(name)


def list_metrics() -> list[MetricDefinition]:
    return list(_METRICS.values())
