"""M1 契约与金融计算测试:覆盖退出条件的全部边界形态。

零分母 / 缺失值 / 币种冲突 / 累计口径 / 修订时间(设计 §17 M1)。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finance_agent.adapters.data.fixture_source import FixtureMetricSource
from finance_agent.contracts.observation import MetricObservation
from finance_agent.finance.calculations import GROWTH_FORMULA_VERSION, calculate_growth
from finance_agent.finance.comparability import comparability_issues

AS_OF = datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)  # 默认任务截止
SRC = FixtureMetricSource()


def obs(oid: str, **kw) -> MetricObservation:
    base = {
        "observation_id": oid,
        "entity_id": "demo-company-a",
        "metric": "net_profit",
        "value": Decimal(100),
        "unit": "元",
        "currency": "CNY",
        "basis": "cumulative",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 6, 30),
        "scope": "合并报表",
        "available_at": datetime(2026, 7, 28, tzinfo=UTC),
        "retrieved_at": datetime(2026, 8, 1, tzinfo=UTC),
        "source_id": "fixture/test",
        "revision_id": "v1",
    }
    base.update(kw)
    return MetricObservation(**base)


class TestObservationContract:
    def test_zero_and_missing_are_distinct(self):
        zero = obs("t-zero", value=Decimal(0))
        missing = obs("t-missing", value=None, note="未披露")
        assert zero.value == 0
        assert missing.value is None
        # JSON 边界:Decimal → str 保精度,缺失保持 null
        assert zero.model_dump(mode="json")["value"] == "0"
        assert missing.model_dump(mode="json")["value"] is None

    def test_frozen(self):
        import pydantic

        o = obs("t-frozen")
        with pytest.raises((pydantic.ValidationError, TypeError)):
            o.value = Decimal(1)  # type: ignore[misc]


class TestGrowthBoundaries:
    def test_normal_growth(self):
        cur = obs("t-cur", value=Decimal(272))
        base = obs("t-base", value=Decimal(306), period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.value == Decimal("-0.11111111")
        assert r.formula == "(current - base) / base"
        assert r.formula_version == GROWTH_FORMULA_VERSION
        assert r.input_observation_ids == ["t-cur", "t-base"]
        assert not r.caveats

    def test_zero_denominator_returns_reason_not_exception(self):
        cur = obs("t-cur", value=Decimal(350))
        base = obs("t-base-zero", value=Decimal(0), period_start=date(2024, 1, 1), period_end=date(2024, 6, 30), available_at=datetime(2024, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.value is None
        assert r.non_computable_reason == "ZERO_DENOMINATOR"

    def test_missing_input(self):
        cur = obs("t-cur-missing", value=None, note="未披露")
        base = obs("t-base-ok", value=Decimal(100), period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.value is None
        assert r.non_computable_reason == "MISSING_INPUT"

    def test_negative_base_computes_with_caveat(self):
        cur = obs("t-cur-neg", value=Decimal(55))
        base = obs("t-base-neg", value=Decimal(-12), period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.value == Decimal("-5.58333333")
        assert any(c.startswith("NEGATIVE_BASE") for c in r.caveats)


class TestComparability:
    def test_basis_conflict_cumulative_vs_single_quarter(self):
        cur = obs("t-sq", basis="single_quarter", period_start=date(2026, 4, 1), period_end=date(2026, 6, 30))
        base = obs("t-cum", basis="cumulative", period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.non_computable_reason == "INCOMPARABLE_INPUTS"
        assert any("期间基准" in i for i in r.issues)

    def test_scope_conflict_consolidated_vs_parent(self):
        cur = obs("t-parent", scope="母公司报表")
        base = obs("t-consol", scope="合并报表", period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        issues = comparability_issues(cur, base)
        assert any("报表口径" in i for i in issues)

    def test_currency_conflict(self):
        cur = obs("t-usd", currency="USD", unit="美元")
        base = obs("t-cny", currency="CNY", period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), available_at=datetime(2025, 7, 28, tzinfo=UTC))
        r = calculate_growth(cur, base)
        assert r.non_computable_reason == "INCOMPARABLE_INPUTS"
        assert any("币种" in i for i in r.issues)

    def test_period_shape_conflict(self):
        # H1(6 个月)对 FY(12 个月):同为 cumulative 也无法比
        cur = obs("t-h1")
        base = obs("t-fy", value=Decimal(780), period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), available_at=datetime(2026, 1, 28, tzinfo=UTC))
        issues = comparability_issues(cur, base)
        assert any("期间长度" in i for i in issues)


class TestFixtureRevisionSelection:
    def test_revision_selected_by_as_of(self):
        # 07-28 v1=296M;08-15 v2=272M
        july = SRC.get_observations(
            entity_id="demo-company-a", metric="net_profit", basis="cumulative",
            period_start=date(2026, 1, 1), period_end=date(2026, 6, 30),
            as_of=datetime(2026, 8, 1, tzinfo=UTC),
        )
        august = SRC.get_observations(
            entity_id="demo-company-a", metric="net_profit", basis="cumulative",
            period_start=date(2026, 1, 1), period_end=date(2026, 6, 30), as_of=AS_OF,
        )
        assert [o.observation_id for o in july if o.observation_id.startswith("obs-a-np-cum-2026h1") and o.scope == "合并报表"] == ["obs-a-np-cum-2026h1-v1"]
        assert [o.observation_id for o in august if o.observation_id.startswith("obs-a-np-cum-2026h1") and o.scope == "合并报表"] == ["obs-a-np-cum-2026h1-v2"]

    def test_observation_not_yet_available_returns_none(self):
        late = SRC.get_observation("obs-b-np-cum-2026h1", as_of=AS_OF)
        assert late is None
        after = SRC.get_observation("obs-b-np-cum-2026h1", as_of=datetime(2026, 9, 5, tzinfo=UTC))
        assert after is not None
