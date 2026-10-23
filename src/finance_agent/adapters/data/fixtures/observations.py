"""三家样本公司的财务观测 fixture。

覆盖 M1 退出条件要求的边界形态:
- 修订:公司A 2026H1 累计净利润 v1(07-28)/v2(08-15),2026Q1 单季净利润 v1/v2;
- 币种冲突:公司C 以 USD 报告,与 A/B 的 CNY 不可比;
- 零基数:公司B 2024H1 收入为 0(新设主体,披露为零,非缺失);
- 负基数:公司C 2025H1 净利润为负(扭亏场景);
- 缺失值:公司B 2026H1 毛利润 value=None(未披露,与零区分);
- 时间边界:公司B 2026H1 净利润 available_at=2026-09-01,晚于默认任务
  截止(2026-08-31)时不可见;
- 报表口径:公司A 另有母公司口径净利润一行,与合并口径不可比。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.contracts.observation import (
    SCOPE_CONSOLIDATED,
    SCOPE_PARENT,
    Basis,
    MetricObservation,
)

RETRIEVED_AT = datetime(2026, 10, 24, tzinfo=UTC)


def _utc(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


def _o(
    observation_id: str,
    entity_id: str,
    metric: str,
    value: str | None,
    *,
    currency: str,
    unit: str,
    basis: Basis,
    period: tuple[date, date],
    available_at: datetime,
    revision_id: str = "v1",
    scope: str = SCOPE_CONSOLIDATED,
    note: str | None = None,
) -> MetricObservation:
    return MetricObservation(
        observation_id=observation_id,
        entity_id=entity_id,
        metric=metric,
        value=None if value is None else Decimal(value),
        unit=unit,
        currency=currency,
        basis=basis,
        period_start=period[0],
        period_end=period[1],
        scope=scope,
        available_at=available_at,
        retrieved_at=RETRIEVED_AT,
        source_id=f"fixture/{entity_id}/{metric}",
        revision_id=revision_id,
        note=note,
    )


def _h1(y: int) -> tuple[date, date]:
    return (date(y, 1, 1), date(y, 6, 30))


def _q1(y: int) -> tuple[date, date]:
    return (date(y, 1, 1), date(y, 3, 31))


def _q2(y: int) -> tuple[date, date]:
    return (date(y, 4, 1), date(y, 6, 30))


def _fy(y: int) -> tuple[date, date]:
    return (date(y, 1, 1), date(y, 12, 31))


def build_observation_fixtures() -> list[MetricObservation]:
    a, b, c = "demo-company-a", "demo-company-b", "demo-company-c"
    obs: list[MetricObservation] = []

    # --- 公司A(CNY,合并报表) ---
    obs += [
        _o("obs-a-rev-cum-2025h1", a, "revenue", "3700000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2025), available_at=_utc(2025, 7, 28)),
        _o("obs-a-rev-cum-2025fy", a, "revenue", "9200000000", currency="CNY", unit="元", basis="cumulative", period=_fy(2025), available_at=_utc(2026, 1, 28)),
        _o("obs-a-rev-cum-2026h1", a, "revenue", "4300000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 7, 28)),
        _o("obs-a-np-cum-2025h1", a, "net_profit", "306000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2025), available_at=_utc(2025, 7, 28)),
        _o("obs-a-np-cum-2025fy", a, "net_profit", "780000000", currency="CNY", unit="元", basis="cumulative", period=_fy(2025), available_at=_utc(2026, 1, 28)),
        _o("obs-a-np-cum-2026h1-v1", a, "net_profit", "296000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 7, 28), revision_id="v1"),
        _o("obs-a-np-cum-2026h1-v2", a, "net_profit", "272000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 8, 15), revision_id="v2", note="2026 年半年度业绩更正公告:净利润下调 2400 万元"),
        _o("obs-a-rev-sq-2026q1", a, "revenue", "1400000000", currency="CNY", unit="元", basis="single_quarter", period=_q1(2026), available_at=_utc(2026, 4, 28)),
        _o("obs-a-rev-sq-2026q2", a, "revenue", "2900000000", currency="CNY", unit="元", basis="single_quarter", period=_q2(2026), available_at=_utc(2026, 7, 28)),
        _o("obs-a-np-sq-2026q1-v1", a, "net_profit", "112000000", currency="CNY", unit="元", basis="single_quarter", period=_q1(2026), available_at=_utc(2026, 4, 28), revision_id="v1"),
        _o("obs-a-np-sq-2026q1-v2", a, "net_profit", "98000000", currency="CNY", unit="元", basis="single_quarter", period=_q1(2026), available_at=_utc(2026, 5, 30), revision_id="v2", note="一季报更正公告:净利润由 1.12 亿调整为 0.98 亿"),
        _o("obs-a-np-sq-2026q2", a, "net_profit", "174000000", currency="CNY", unit="元", basis="single_quarter", period=_q2(2026), available_at=_utc(2026, 7, 28)),
        # 母公司口径:与合并口径不可比的用例
        _o("obs-a-np-cum-2026h1-parent", a, "net_profit", "265000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 7, 28), scope=SCOPE_PARENT),
    ]

    # --- 公司B(CNY,披露晚) ---
    obs += [
        _o("obs-b-rev-cum-2024h1", b, "revenue", "0", currency="CNY", unit="元", basis="cumulative", period=_h1(2024), available_at=_utc(2024, 7, 28), note="新设主体,披露为零(非缺失)"),
        _o("obs-b-rev-cum-2025h1", b, "revenue", "350000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2025), available_at=_utc(2025, 8, 28)),
        _o("obs-b-rev-cum-2026h1", b, "revenue", "2450000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 8, 28)),
        _o("obs-b-np-cum-2026h1", b, "net_profit", "179000000", currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 9, 1), note="半年报于 2026-09-01 披露"),
        _o("obs-b-gp-cum-2026h1", b, "gross_profit", None, currency="CNY", unit="元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 8, 28), note="未披露毛利润,缺失而非零"),
    ]

    # --- 公司C(USD) ---
    obs += [
        _o("obs-c-np-cum-2025h1", c, "net_profit", "-12000000", currency="USD", unit="美元", basis="cumulative", period=_h1(2025), available_at=_utc(2025, 8, 20), note="亏损(负基数用例)"),
        _o("obs-c-np-cum-2026h1", c, "net_profit", "55000000", currency="USD", unit="美元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 8, 20), note="扭亏为盈"),
        _o("obs-c-rev-cum-2026h1", c, "revenue", "610000000", currency="USD", unit="美元", basis="cumulative", period=_h1(2026), available_at=_utc(2026, 8, 20)),
    ]

    ids = [o.observation_id for o in obs]
    assert len(ids) == len(set(ids)), "fixture 观测 ID 必须唯一"
    return obs
