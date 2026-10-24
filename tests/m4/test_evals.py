"""M4 离线测试:用例契约、评分器、D 管道、akshare 适配器(注入假数据,无网络)。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.adapters.data.akshare_source import AkshareMetricSource
from finance_agent.evals.cases import EvalCase, Expectation, load_cases
from finance_agent.evals.pipeline_d import run_pipeline_d
from finance_agent.evals.runner import CaseResult
from finance_agent.evals.scorers import score_case

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
AS_OF = "2026-08-31T23:59:59+08:00"


def _case(**exp) -> EvalCase:
    return EvalCase(
        case_id="t-1", task_type="earnings", objective="o",
        entity_ids=["demo-company-a"], as_of=AS_OF,
        expectation=Expectation(**exp),
    )


def _result(cr_status="succeeded", refs=None, text="", loaded=None, outputs=None) -> CaseResult:
    result = {
        "summary": text, "key_findings": [{"statement": text, "kind": "fact", "refs": refs or []}],
        "metric_refs": refs or [], "calculation_refs": [], "evidence_refs": [],
    }
    return CaseResult(case_id="t-1", group="C", status=cr_status, result=result,
                      loaded_skills=loaded or [], tool_outputs=outputs or [])


class TestScorers:
    async def test_case_files_valid(self):
        cases = load_cases(PROJECT_ROOT / "evals" / "cases" / "dev")
        assert len(cases) == 9
        types = {c.task_type for c in cases}
        assert types == {"earnings", "announcement", "peer", "boundary"}

    async def test_citation_invalid_detected(self):
        case = _case(required_refs=["obs-a-np-cum-2026h1-v2"])
        outputs = [{
            "tool": "finance.get_metrics", "ok": True,
            "result": {"observations": [{
                "observation_id": "obs-a-np-cum-2026h1-v2",
                "available_at": "2026-08-15T00:00:00Z", "value": "272000000",
            }]},
            "error": None,
        }]
        cr = _result(refs=["obs-a-np-cum-2026h1-v2", "obs-ghost"], text="x", outputs=outputs)
        s = score_case(case, cr)
        assert not s.citation_valid and s.invalid_refs == ["obs-ghost"]

    async def test_document_version_ref_is_valid(self):
        """引用 docv-*(文档版本)与引用其下证据 ID 等价(M4 报告 §3 改进)。"""
        outputs = [{
            "tool": "documents.search", "ok": True,
            "result": {"hits": [{
                "evidence": {"evidence_id": "chk-a-p1-1", "available_at": "2026-05-30T00:00:00Z"},
                "document": {"version_id": "docv-a-q1-correct-v1", "available_at": "2026-05-30T00:00:00Z"},
            }]},
            "error": None,
        }]
        case = _case()
        ok_cr = _result(refs=["docv-a-q1-correct-v1"], outputs=outputs)
        assert score_case(case, ok_cr).citation_valid
        # 晚于 as_of 的版本引用仍无效
        late_outputs = [{
            "tool": "documents.search", "ok": True,
            "result": {"hits": [{"document": {"version_id": "docv-future", "available_at": "2026-12-01T00:00:00Z"}}]},
            "error": None,
        }]
        bad_cr = _result(refs=["docv-future"], outputs=late_outputs)
        assert not score_case(case, bad_cr).citation_valid

    async def test_time_violation_counted(self):
        outputs = [{
            "tool": "finance.get_metrics", "ok": True,
            "result": {"observations": [{
                "observation_id": "obs-late", "available_at": "2026-12-01T00:00:00Z",
            }]},
            "error": None,
        }]
        s = score_case(_case(), _result(outputs=outputs))
        assert s.time_violations == 1

    async def test_forbidden_number_blocks(self):
        case = _case(forbidden_numbers=["179000000"])
        s = score_case(case, _result(text="B 公司净利润 179000000 元"))
        assert not s.numeric_ok and s.fabricated_numbers == ["179000000"]

    async def test_expected_number_any_hit(self):
        case = _case(expected_numbers=["-11.11", "-0.1111"])
        s = score_case(case, _result(refs=[], text="同比下降 11.11 个百分点,即 -11.11%"))
        assert s.numeric_ok

    async def test_skill_hint_c_group(self):
        case = _case(skill_hint=["earnings-analysis"])
        ok_case = score_case(case, _result(loaded=["earnings-analysis"]))
        bad_case = score_case(case, _result(loaded=["peer-comparison"]))
        assert ok_case.skill_ok and not bad_case.skill_ok

    async def test_completion_requires_everything(self):
        case = _case(required_refs=["obs-x"], required_keywords=["更正"])
        no_kw = score_case(case, _result(refs=["obs-x"], text="无关键词"))
        assert not no_kw.completed and not no_kw.partial  # 硬条件缺失不算部分完成
        # 硬条件全过但 Skill 不合理 → 部分完成
        hint_case = _case(skill_hint=["earnings-analysis"])
        partial = score_case(hint_case, _result(refs=[], text="x", loaded=["peer-comparison"]))
        assert not partial.completed and partial.partial


class TestPipelineD:
    async def test_d_applicable_earnings_only(self):
        assert run_pipeline_d(_case()).status == "succeeded"
        peer = EvalCase(case_id="p", task_type="peer", objective="o", entity_ids=["demo-company-a"],
                        as_of=AS_OF, expectation=Expectation())
        assert run_pipeline_d(peer).status == "not_applicable"

    async def test_d_uses_shape_matched_base(self):
        cr = run_pipeline_d(_case())
        assert cr.result["metric_refs"] == ["obs-a-np-cum-2026h1-v2", "obs-a-np-cum-2025h1"]
        assert cr.result["calculation_refs"]
        assert "-11.11" in cr.result["summary"]


class _Series:
    def __init__(self, values: list):
        self.values = values

    def __eq__(self, code):  # noqa: PLR6121
        return [v == code for v in self.values]


class FakeDF:
    """极简 DataFrame 替身:支持 df[列名] == code 与 df[布尔掩码] 与 iterrows。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __getitem__(self, key):
        if isinstance(key, str):
            return _Series([r.get(key) for r in self.rows])
        if isinstance(key, list):
            return FakeDF([r for r, m in zip(self.rows, key) if m])
        return FakeDF(self.rows)

    def iterrows(self):
        for r in self.rows:
            yield 0, r


class TestAkshareSource:
    def _source(self):
        rows = [
            {"股票代码": "600519", "营业总收入-营业总收入": 9.2278e10, "净利润-净利润": 4.45168e10,
             "最新公告日期": "2026-08-15"},
            {"股票代码": "000858", "营业总收入-营业总收入": 2.8416e10, "净利润-净利润": 8.7529e9,
             "最新公告日期": "2026-08-29"},
        ]
        return AkshareMetricSource(fetcher=lambda d: FakeDF(rows))

    async def test_mapping_and_asof_boundary(self):
        src = self._source()
        obs = src.get_observations(entity_id="cn-600519", metric="net_profit",
                                   basis="cumulative", period_start=date(2026, 4, 1),
                                   period_end=date(2026, 6, 30),
                                   as_of=datetime(2026, 8, 31, tzinfo=UTC))
        assert len(obs) == 1
        o = obs[0]
        assert o.observation_id == "obs-ak-600519-net_profit-20260630"
        assert o.basis == "cumulative" and o.scope == "合并报表"
        assert o.currency == "CNY" and o.value == Decimal(str(4.45168e10))
        assert o.period_start == date(2026, 1, 1) and o.period_end == date(2026, 6, 30)

        # 8-14 边界:茅台 8-15 公告不可见;五粮液 8-29 也不可见
        early = src.get_observations(entity_id="cn-600519", metric="net_profit",
                                     as_of=datetime(2026, 8, 14, tzinfo=UTC))
        assert early == []
        late = src.get_observations(entity_id="cn-000858", metric="net_profit",
                                    period_start=date(2026, 4, 1), period_end=date(2026, 6, 30),
                                    as_of=datetime(2026, 8, 31, tzinfo=UTC))
        assert len(late) == 1

    async def test_get_observation_by_id(self):
        src = self._source()
        o = src.get_observation("obs-ak-600519-net_profit-20260630", as_of=datetime(2026, 9, 1, tzinfo=UTC))
        assert o is not None and o.entity_id == "cn-600519"
        assert src.get_observation("obs-ghost", as_of=datetime(2026, 9, 1, tzinfo=UTC)) is None
