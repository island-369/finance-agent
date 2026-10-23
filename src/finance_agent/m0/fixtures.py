"""M0 合成金融观测样本。

全部为合成数据,仅用于驱动底座实验,不代表任何真实公司。
每条观测携带 available_at(该版本可公开获知的时间),用于验证 as_of 时间边界:
工具只返回 available_at <= as_of 的版本;同一报告期存在多版本时取截止时间内
最新的修订版(设计 §8.4)。
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

_CST = timezone(timedelta(hours=8))


def _cst(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=_CST)


def _obs(
    n: int,
    entity: str,
    metric: str,
    value: str,
    period: tuple[str, str],
    available_at: datetime,
    revision: str = "v1",
) -> dict:
    return {
        "observation_id": f"obs-{n:03d}",
        "entity_id": entity,
        "metric": metric,
        "value": value,
        "unit": "元",
        "currency": "CNY",
        "period_start": period[0],
        "period_end": period[1],
        "scope": "合并报表",
        "available_at": available_at.isoformat(),
        "source_id": f"fixture/{entity}/{metric}",
        "revision_id": revision,
    }


def _quarter_start_end(year: int, q: int) -> tuple[str, str]:
    start_month = 3 * (q - 1) + 1
    end_month = start_month + 2
    last_day = calendar.monthrange(year, end_month)[1]
    return (
        f"{year}-{start_month:02d}-01",
        f"{year}-{end_month:02d}-{last_day:02d}",
    )


def build_default_observations() -> list[dict]:
    """三家样本公司的季度收入与净利润(累计口径:年初至报告期末)。"""
    observations: list[dict] = []
    n = 1

    # demo-company-a:2025Q1–2026Q2;2026Q1 净利润在 2026-05-30 发布修订版 v2
    for year, q, revenue, profit in [
        (2025, 1, "1200000000.00", "96000000.00"),
        (2025, 2, "2500000000.00", "210000000.00"),
        (2025, 3, "3900000000.00", "351000000.00"),
        (2025, 4, "5300000000.00", "477000000.00"),
        (2026, 1, "1400000000.00", "112000000.00"),
        (2026, 2, "2900000000.00", "174000000.00"),
    ]:
        period = _quarter_start_end(year, q)
        # 财报约在报告期后 28 天可获得
        available = _cst(year, min(12, 3 * q + 1), 28)
        observations.append(_obs(n, "demo-company-a", "revenue", revenue, period, available))
        n += 1
        observations.append(_obs(n, "demo-company-a", "net_profit", profit, period, available))
        n += 1
    # 2026Q1 净利润修订:v1 初值 112000000(2026-04-28),v2 修订 98000000(2026-05-30)
    observations.append(
        _obs(
            n,
            "demo-company-a",
            "net_profit",
            "98000000.00",
            _quarter_start_end(2026, 1),
            _cst(2026, 5, 30),
            revision="v2",
        )
    )
    n += 1

    # demo-company-b / demo-company-c:仅 2026 上半年,用于同业比较后续验证
    for entity, rev_1, prof_1, rev_2, prof_2 in [
        ("demo-company-b", "800000000.00", "64000000.00", "1650000000.00", "115000000.00"),
        ("demo-company-c", "2100000000.00", "189000000.00", "4400000000.00", "396000000.00"),
    ]:
        for (year, q), revenue, profit in [
            ((2026, 1), rev_1, prof_1),
            ((2026, 2), rev_2, prof_2),
        ]:
            period = _quarter_start_end(year, q)
            available = _cst(year, min(12, 3 * q + 1), 28)
            observations.append(_obs(n, entity, "revenue", revenue, period, available))
            n += 1
            observations.append(_obs(n, entity, "net_profit", profit, period, available))
            n += 1

    return observations


DEFAULT_OBSERVATIONS = build_default_observations()
