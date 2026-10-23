"""akshare 真实数据源(东方财富业绩报表)→ MetricObservation 契约。

公司与报告期(设计 §2.2:一个行业、三家公司——白酒):
- cn-600519 贵州茅台 / cn-000858 五粮液 / cn-000568 泸州老窖

契约映射与已知限制(接入记录见 docs/M4-数据源接入记录.md):
- basis 固定 cumulative(业绩报表为年初至报告期末累计);scope 合并报表。
- available_at = 最新公告日期,时间精度为"日"(§8.4 记录精度,不虚构精确时刻)。
- 业绩报表只提供"最新值 + 最新公告日期":无历史修订版本链(fixture 有),
  修订语义以最新公告近似,如实降级。
- 数值来自上游浮点,Decimal(str(value)) 转换保留上游精度(上游即浮点,
  精度损失在数据源侧,记录在案)。
- fetcher 可注入(测试无网络;生产默认 ak.stock_yjbb_em)。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.contracts.observation import SCOPE_CONSOLIDATED, MetricObservation

REAL_ENTITIES = {
    "cn-600519": ("600519", "贵州茅台"),
    "cn-000858": ("000858", "五粮液"),
    "cn-000568": ("000568", "泸州老窖"),
}
_METRIC_COLUMNS = {
    "revenue": "营业总收入-营业总收入",
    "net_profit": "净利润-净利润",
}
_QUARTER_ENDS = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}


def _default_fetcher(report_date: str):
    import akshare as ak

    return ak.stock_yjbb_em(date=report_date)


class AkshareMetricSource:
    def __init__(self, fetcher: Callable[[str], object] | None = None) -> None:
        self._fetcher = fetcher or _default_fetcher
        self._cache: dict[str, object] = {}
        self.retrieved_at = datetime.now(UTC)

    def _df(self, report_date: str):
        if report_date not in self._cache:
            self._cache[report_date] = self._fetcher(report_date)
        return self._cache[report_date]

    def _quarter_dates(self, period_start: date | None, period_end: date | None) -> list[str]:
        start_year = (period_start or date(2024, 1, 1)).year
        end_date = period_end or date.today()
        dates = []
        for year in range(start_year, end_date.year + 1):
            for mmdd in _QUARTER_ENDS.values():
                d = datetime.strptime(f"{year}{mmdd}", "%Y%m%d").date()
                if (period_start is None or d >= period_start) and d <= end_date:
                    dates.append(f"{year}{mmdd}")
        return sorted(dates)

    def get_observations(
        self, *, entity_id: str, metric: str, basis=None, scope=None,
        period_start=None, period_end=None, as_of: datetime,
    ) -> list[MetricObservation]:
        if entity_id not in REAL_ENTITIES:
            return []
        code, name = REAL_ENTITIES[entity_id]
        col = _METRIC_COLUMNS.get(metric)
        if col is None:
            return []

        results: list[MetricObservation] = []
        for report_date in self._quarter_dates(period_start, period_end):
            year, mmdd = report_date[:4], report_date[4:]
            df = self._df(report_date)
            try:
                rows = df[df["股票代码"] == code]
            except Exception:  # noqa: BLE001 — 非 DataFrame 返回按无数据处理
                rows = []
            for _, row in rows.iterrows():
                announced = row.get("最新公告日期")
                value = row.get(col)
                if announced is None or value is None or (isinstance(value, float) and math.isnan(value)):
                    continue
                available_at = datetime.strptime(str(announced)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                if available_at > as_of:
                    continue
                dec = Decimal(str(value))
                results.append(MetricObservation(
                    observation_id=f"obs-ak-{code}-{metric}-{report_date}",
                    entity_id=entity_id,
                    metric=metric,
                    value=dec,
                    unit="元", currency="CNY",
                    basis="cumulative",
                    period_start=date(int(year), 1, 1),
                    period_end=datetime.strptime(f"{year}{mmdd}", "%Y%m%d").date(),
                    scope=SCOPE_CONSOLIDATED,
                    available_at=available_at,
                    retrieved_at=self.retrieved_at,
                    source_id=f"akshare/yjbb_em/{name}",
                    revision_id="latest",
                    note=f"上游:{name} {report_date} 业绩报表;时间精度日;无历史修订链",
                ))
        return sorted(results, key=lambda o: o.period_end)

    def get_observation(self, observation_id: str, *, as_of: datetime) -> MetricObservation | None:
        # obs-ak-<code>-<metric>-<yyyymmdd>
        parts = observation_id.split("-")
        if len(parts) != 5 or parts[0] != "obs" or parts[1] != "ak":
            return None
        _, _, code, metric, report_date = parts
        entity = next((k for k, (c, _) in REAL_ENTITIES.items() if c == code), None)
        if entity is None:
            return None
        obs = self.get_observations(
            entity_id=entity, metric=metric, as_of=as_of,
            period_start=datetime.strptime(report_date[:4], "%Y").date(),
            period_end=datetime.strptime(report_date, "%Y%m%d").date(),
        )
        return next((o for o in obs if o.observation_id == observation_id), None)
