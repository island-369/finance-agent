"""M1 工具与注册中心测试:五个工具单独调用 + 结构化错误 + 时间边界。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from finance_agent.bootstrap import build_default_registry
from finance_agent.contracts.common import (
    BUDGET_EXCEEDED,
    DATA_NOT_FOUND,
    INCOMPARABLE_METRICS,
    INVALID_ARGUMENT,
)
from finance_agent.contracts.task import TaskContext

AS_OF = datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)
CTX = TaskContext(as_of=AS_OF)


@pytest.fixture()
def registry():
    return build_default_registry()


def call(registry, name, args, ctx=CTX):
    return registry.call(name, args, ctx)


class TestRegistry:
    def test_five_tools_registered(self, registry):
        names = {s.name for s in registry.list_tools()}
        assert names == {
            "documents.search",
            "documents.read",
            "finance.get_metrics",
            "finance.calculate_growth",
            "finance.compare_peers",
        }

    def test_unknown_tool_structured_error(self, registry):
        r = call(registry, "no.such_tool", {})
        assert not r.ok and r.error.code == INVALID_ARGUMENT
        assert any("finance.get_metrics" in a for a in r.error.alternatives)

    def test_invalid_arguments_validated(self, registry):
        r = call(registry, "finance.get_metrics", {"entity_id": "demo-company-a"})  # 缺 metric
        assert not r.ok and r.error.code == INVALID_ARGUMENT
        assert r.error.detail["errors"]

    def test_budget_precheck(self, registry):
        ctx = TaskContext(as_of=AS_OF, budget_check=lambda: False)
        r = call(registry, "finance.get_metrics", {"entity_id": "demo-company-a", "metric": "revenue"}, ctx)
        assert not r.ok and r.error.code == BUDGET_EXCEEDED


class TestGetMetrics:
    def test_revision_and_asof_boundary(self, registry):
        r = call(registry, "finance.get_metrics", {
            "entity_id": "demo-company-a", "metric": "net_profit",
            "basis": "cumulative", "period_start": "2026-01-01", "period_end": "2026-06-30",
        })
        assert r.ok
        obs_list = r.payload.observations
        assert [o.observation_id for o in obs_list] == ["obs-a-np-cum-2026h1-v2"]
        assert str(obs_list[0].value) == "272000000"

    def test_asof_cannot_exceed_task_cutoff(self, registry):
        r = call(registry, "finance.get_metrics", {
            "entity_id": "demo-company-a", "metric": "revenue",
            "as_of": "2026-12-31T00:00:00+00:00",
        })
        assert not r.ok and r.error.code == INVALID_ARGUMENT
        assert r.error.detail["violation"] == "as_of_exceeds_task_cutoff"

    def test_data_not_found_with_alternatives(self, registry):
        r = call(registry, "finance.get_metrics", {"entity_id": "demo-company-b", "metric": "net_profit", "basis": "cumulative"})
        assert not r.ok and r.error.code == DATA_NOT_FOUND  # 2026-09-01 才披露

    def test_narrower_asof_allowed(self, registry):
        r = call(registry, "finance.get_metrics", {
            "entity_id": "demo-company-a", "metric": "net_profit", "basis": "cumulative",
            "as_of": "2026-08-01T00:00:00+00:00",
        })
        assert r.ok
        assert r.payload.observations[-1].revision_id == "v1"  # 8-01 只见 v1


class TestCalculateGrowthTool:
    def test_growth_via_tool_records_inputs(self, registry):
        r = call(registry, "finance.calculate_growth", {
            "current_observation_id": "obs-a-np-cum-2026h1-v2",
            "base_observation_id": "obs-a-np-cum-2025h1",
        })
        assert r.ok
        assert str(r.payload.value) == "-0.11111111"
        assert r.payload.formula_version == "growth.yoy@1"

    def test_zero_denominator_via_fixture(self, registry):
        r = call(registry, "finance.calculate_growth", {
            "current_observation_id": "obs-b-rev-cum-2025h1",
            "base_observation_id": "obs-b-rev-cum-2024h1",
        })
        assert r.ok and r.payload.value is None
        assert r.payload.non_computable_reason == "ZERO_DENOMINATOR"

    def test_negative_base_via_fixture(self, registry):
        r = call(registry, "finance.calculate_growth", {
            "current_observation_id": "obs-c-np-cum-2026h1",
            "base_observation_id": "obs-c-np-cum-2025h1",
        })
        assert r.ok and str(r.payload.value) == "-5.58333333"
        assert any("NEGATIVE_BASE" in c for c in r.payload.caveats)

    def test_unavailable_observation_id_rejected(self, registry):
        # v2 修订在 08-15 才可得;把 as_of 收窄到 08-01 再引用它必须失败
        r = call(registry, "finance.calculate_growth", {
            "current_observation_id": "obs-a-np-cum-2026h1-v2",
            "base_observation_id": "obs-a-np-cum-2025h1",
            "as_of": "2026-08-01T00:00:00+00:00",
        })
        assert not r.ok and r.error.code == DATA_NOT_FOUND
        assert "obs-a-np-cum-2026h1-v2" in r.error.detail["missing_observation_ids"]

    def test_scope_conflict_via_fixture(self, registry):
        r = call(registry, "finance.calculate_growth", {
            "current_observation_id": "obs-a-np-cum-2026h1-parent",
            "base_observation_id": "obs-a-np-cum-2025h1",
        })
        assert r.ok and r.payload.non_computable_reason == "INCOMPARABLE_INPUTS"
        assert any("报表口径" in i for i in r.payload.issues)


class TestComparePeers:
    def _h1_args(self, entity_ids):
        return {
            "entity_ids": entity_ids, "metric": "revenue", "basis": "cumulative",
            "period_start": "2026-01-01", "period_end": "2026-06-30",
        }

    def test_aligned_table_with_missing_note(self, registry):
        # B 净利润 09-01 才发布 → 行级缺失说明,不影响 A 返回
        r = call(registry, "finance.compare_peers", {
            "entity_ids": ["demo-company-a", "demo-company-b"], "metric": "net_profit",
            "basis": "cumulative", "period_start": "2026-01-01", "period_end": "2026-06-30",
        })
        assert r.ok
        rows = {row.entity_id: row for row in r.payload.rows}
        assert rows["demo-company-a"].value == "272000000"
        assert rows["demo-company-b"].missing_reason is not None

    def test_currency_conflict_is_structured_error(self, registry):
        r = call(registry, "finance.compare_peers", self._h1_args(["demo-company-a", "demo-company-c"]))
        assert not r.ok and r.error.code == INCOMPARABLE_METRICS
        assert r.error.detail["currency_conflicts"]
        assert any("按币种分组" in a for a in r.error.alternatives)

    def test_both_present_aligned(self, registry):
        r = call(registry, "finance.compare_peers", self._h1_args(["demo-company-a", "demo-company-b"]))
        assert r.ok
        rows = {row.entity_id: row for row in r.payload.rows}
        assert rows["demo-company-a"].value == "4300000000"
        assert rows["demo-company-b"].value == "2450000000"

    def test_missing_value_row(self, registry):
        # B 毛利润存在但 value=None → 行级缺失而非整表失败
        r = call(registry, "finance.compare_peers", {
            "entity_ids": ["demo-company-a", "demo-company-b"], "metric": "gross_profit",
            "basis": "cumulative", "period_start": "2026-01-01", "period_end": "2026-06-30",
        })
        assert r.ok
        rows = {row.entity_id: row for row in r.payload.rows}
        assert rows["demo-company-a"].missing_reason is not None  # A 无毛利观测
        assert rows["demo-company-b"].missing_reason is not None  # B 未披露(缺失)


class TestDocumentsTools:
    def test_search_finds_correction_with_time_boundary(self, registry):
        # “内部交易抵销遗漏”只出现在更正公告中
        r = call(registry, "documents.search", {"query": "内部交易抵销", "entity_ids": ["demo-company-a"]})
        assert r.ok
        assert all(h.document.version_id == "docv-a-q1-correct-v1" for h in r.payload.hits)

        # 更正公告 05-30 才可得:05-01 检索不到该内容
        early = call(registry, "documents.search", {
            "query": "内部交易抵销", "entity_ids": ["demo-company-a"],
            "as_of": "2026-05-01T00:00:00+00:00",
        })
        assert not early.ok and early.error.code == DATA_NOT_FOUND

    def test_search_picks_latest_document_version(self, registry):
        # 业绩预告 v1(07-10)与 v2(07-12):08-31 时点只应命中 v2
        r = call(registry, "documents.search", {"query": "业绩预告 净利润", "entity_ids": ["demo-company-a"]})
        assert r.ok
        assert all(h.document.version_id != "docv-a-h1-preview-v1" for h in r.payload.hits)
        assert any(h.document.version_id == "docv-a-h1-preview-v2" for h in r.payload.hits)

    def test_read_by_chunk_id(self, registry):
        search = call(registry, "documents.search", {"query": "更正 112,000,000"})
        assert search.ok
        hit = search.payload.hits[0]
        r = call(registry, "documents.read", {"chunk_id": hit.evidence.evidence_id})
        assert r.ok
        assert "98,000,000" in r.payload.chunk.text
        assert r.payload.document.content_sha256

    def test_read_by_location(self, registry):
        r = call(registry, "documents.read", {
            "document_version_id": "docv-a-annual-2025-v1", "page": 1, "paragraph": 1,
        })
        assert r.ok and "92.00" in r.payload.chunk.text

    def test_read_unavailable_version_rejected(self, registry):
        # B 半年报 09-01 发布,默认 as_of 不可读
        r = call(registry, "documents.read", {
            "document_version_id": "docv-b-h1-2026-v1", "page": 2, "paragraph": 1,
        })
        assert not r.ok and r.error.code == DATA_NOT_FOUND

    def test_json_serialization_roundtrip(self, registry):
        r = call(registry, "finance.get_metrics", {"entity_id": "demo-company-c", "metric": "net_profit"})
        assert r.ok
        dumped = json.dumps(r.to_dict(), ensure_ascii=False)  # 不抛异常即通过
        assert "obs-c-np-cum-2026h1" in dumped
