"""结果校验链单元测试:引用存在性、计算匹配、数字映射启发式、修复反馈。"""

from __future__ import annotations

from datetime import UTC, datetime

from finance_agent.application.result_validation import (
    build_run_trace,
    render_repair_feedback,
    validate_result,
)

AS_OF = datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)

TOOL_OUTPUTS = [
    {
        "tool": "finance.get_metrics",
        "ok": True,
        "result": {
            "observations": [
                {"observation_id": "obs-a-np-cum-2026h1-v2", "value": "272000000", "available_at": "2026-08-15T00:00:00Z", "unit": "元", "metric": "net_profit"},
                {"observation_id": "obs-a-np-cum-2025h1", "value": "306000000", "available_at": "2025-07-28T00:00:00Z", "unit": "元", "metric": "net_profit"},
                {"observation_id": "obs-a-rev-cum-2026h1", "value": "4300000000", "available_at": "2026-07-28T00:00:00Z", "unit": "元", "metric": "revenue"},
                {"observation_id": "obs-a-rev-cum-2025h1", "value": "3700000000", "available_at": "2025-07-28T00:00:00Z", "unit": "元", "metric": "revenue"},
                # 晚于 as_of 的观测不得进入 trace
                {"observation_id": "obs-future", "value": "1", "available_at": "2026-12-01T00:00:00Z"},
            ]
        },
        "error": None,
    },
    {
        "tool": "finance.calculate_growth",
        "ok": True,
        "result": {"calculation_id": "calc-1", "value": "-0.11111111", "input_observation_ids": ["obs-a-np-cum-2026h1-v2", "obs-a-np-cum-2025h1"]},
        "error": None,
    },
    {
        "tool": "documents.search",
        "ok": True,
        "result": {"hits": [{"evidence": {"evidence_id": "chk-1", "available_at": "2026-05-30T00:00:00Z"},
                              "document": {"version_id": "docv-1", "available_at": "2026-05-30T00:00:00Z"}}]},
        "error": None,
    },
]


def _result(**kw) -> dict:
    base = {
        "objective": "o",
        "summary": "净利润 2.72 亿元,同比下降 11.1%;收入 43.0 亿元,同比增长 16.2%(2026 年)。",
        "key_findings": [
            {"statement": "2026H1 净利润 2.72 亿元(obs-a-np-cum-2026h1-v2),同比下降 11.1%(calc-1)", "kind": "fact", "refs": ["obs-a-np-cum-2026h1-v2", "calc-1"]},
            {"statement": "收入 43.0 亿元(obs-a-rev-cum-2026h1)同比增长 16.2%", "kind": "fact", "refs": ["obs-a-rev-cum-2026h1"]},
        ],
        "metric_refs": ["obs-a-np-cum-2026h1-v2"],
        "calculation_refs": ["calc-1"],
        "evidence_refs": [{"evidence_id": "chk-1", "page": 1, "paragraph": 1}],
    }
    base.update(kw)
    return base


def _validate(**kw):
    return validate_result(_result(**kw), build_run_trace(TOOL_OUTPUTS, as_of=AS_OF))


class TestHappyPath:
    def test_well_referenced_result_passes(self):
        r = _validate()
        assert r.ok, f"hard={r.hard} repairable={r.repairable}"

    def test_time_boundary_excludes_future_obs(self):
        trace = build_run_trace(TOOL_OUTPUTS, as_of=AS_OF)
        assert "obs-future" not in trace.observations
        assert "chk-1" in trace.evidence_ids and "docv-1" in trace.document_version_ids


class TestHardErrors:
    def test_unknown_obs_ref(self):
        r = _validate(metric_refs=["obs-ghost"])
        assert not r.ok and any("obs-ghost" in h for h in r.hard)

    def test_unknown_calc_ref(self):
        r = _validate(calculation_refs=["calc-ghost"])
        assert any("calc-ghost" in h for h in r.hard)

    def test_unknown_evidence_ref(self):
        r = _validate(evidence_refs=[{"evidence_id": "chk-ghost", "page": 1, "paragraph": 1}])
        assert any("chk-ghost" in h for h in r.hard)

    def test_unknown_ref_in_finding(self):
        r = _validate(key_findings=[{"statement": "x", "kind": "fact", "refs": ["obs-nope"]}])
        assert any("obs-nope" in h for h in r.hard)

    def test_empty_result(self):
        r = validate_result({}, build_run_trace(TOOL_OUTPUTS, as_of=AS_OF))
        assert r.hard == ["结果为空"]


class TestRepairable:
    def test_fact_without_refs(self):
        r = _validate(key_findings=[{"statement": "净利润变化", "kind": "fact", "refs": []}])
        assert not r.hard
        assert any("缺少引用" in x for x in r.repairable)

    def test_assumption_without_refs_is_fine(self):
        r = _validate(key_findings=[{"statement": "可能存在成本压力", "kind": "assumption", "refs": []},
                                    {"statement": "2026 年净利润 2.72 亿元", "kind": "fact", "refs": ["obs-a-np-cum-2026h1-v2"]}])
        assert not any("缺少引用" in x for x in r.repairable)

    def test_unmappable_number_flagged(self):
        # 5.55 无法由任何观测/计算/推导得到
        r = _validate(summary="净利润 2.72 亿元,利润率约 5.55%,同比下降 11.1%。")
        assert any("5.55" in x for x in r.repairable)

    def test_derived_margin_number_maps(self):
        # 6.33 = 272000000/4300000000*100(同发现内派生)
        r = _validate(
            key_findings=[{"statement": "净利率 6.33%", "kind": "inference",
                           "refs": ["obs-a-np-cum-2026h1-v2", "obs-a-rev-cum-2026h1"]}])
        assert not any("6.33" in x for x in r.repairable)

    def test_global_pair_derivation_maps_growth(self):
        # 16.2 = (43-37)/37*100;引用只含本期,靠全局同指标对推导
        r = _validate(key_findings=[{"statement": "收入 43.0 亿元同比增长 16.2%", "kind": "fact",
                                     "refs": ["obs-a-rev-cum-2026h1"]}])
        assert not any("16.2" in x for x in r.repairable)

    def test_wan_and_comma_numbers(self):
        # 27,200.0 万 = 272000000 → 万换算;千分位逗号解析
        r = _validate(summary="净利润 27,200.0 万,即 2.72 亿元。")
        assert not any("27200" in x for x in r.repairable)

    def test_year_exempt(self):
        r = _validate(summary="较 2025 年同期变化。")
        assert not any("2025" in x for x in r.repairable)


class TestFeedback:
    def test_feedback_lists_categories(self):
        r = _validate(metric_refs=["obs-ghost"],
                      key_findings=[{"statement": "无引用结论", "kind": "fact", "refs": []}])
        text = render_repair_feedback(r, round_no=1, max_rounds=2)
        assert "第 1/2 轮" in text
        assert "【必须修正·引用错误】" in text
        assert "obs-ghost" in text
        assert "【请修正或改述】" in text
        assert "缺少引用" in text
