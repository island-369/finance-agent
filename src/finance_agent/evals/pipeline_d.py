"""D 组:固定流程基线(确定性代码,无模型)。

设计 §16.2:D 是"一条代表性任务的固定流程基线"——对业绩变化类问题固定执行
取数(最近两个可得累计报告期)→ calculate_growth → 模板渲染结果;不做公告
检索、同业对齐与方法选择。非 earnings 族记 not_applicable(报告按适用子集
统计 D)。直接使用数据源与计算函数,不经模型。
"""

from __future__ import annotations

from datetime import UTC, datetime

from finance_agent.adapters.data.fixture_source import FixtureMetricSource
from finance_agent.contracts.observation import SCOPE_CONSOLIDATED
from finance_agent.contracts.result import ResearchResult
from finance_agent.evals.cases import EvalCase
from finance_agent.evals.runner import CaseResult
from finance_agent.finance.calculations import calculate_growth
from finance_agent.finance.comparability import _period_shape


def run_pipeline_d(case: EvalCase) -> CaseResult:
    res = CaseResult(case_id=case.case_id, group="D")
    if case.task_type != "earnings":
        res.status = "not_applicable"
        res.notes = "固定流程仅覆盖业绩变化类任务(设计 §16.2)"
        return res

    source = FixtureMetricSource()
    as_of = datetime.fromisoformat(case.as_of)
    outputs: list[dict] = []
    findings: list[dict] = []
    metric_refs: list[str] = []
    calc_refs: list[str] = []
    gaps: list[str] = []

    for entity in case.entity_ids:
        obs_list = source.get_observations(
            entity_id=entity, metric="net_profit", basis="cumulative",
            scope=SCOPE_CONSOLIDATED, as_of=as_of,
        )
        outputs.append({
            "tool": "finance.get_metrics", "ok": True,
            "result": {"observations": [o.model_dump(mode="json") for o in obs_list]}, "error": None,
        })
        if len(obs_list) < 2:
            gaps.append(f"{entity}: 累计净利润观测不足两期,固定流程无法计算同比")
            continue
        current = obs_list[-1]
        # 固定规则:基期 = 与本期期间形状一致(同跨度)的更早最近一期
        base = next(
            (o for o in reversed(obs_list[:-1]) if _period_shape(o) == _period_shape(current)),
            None,
        )
        if base is None:
            gaps.append(f"{entity}: 无与本期同跨度的可比基期,固定流程不做变通")
            continue
        metric_refs += [current.observation_id, base.observation_id]
        growth = calculate_growth(current, base)
        outputs.append({
            "tool": "finance.calculate_growth", "ok": True,
            "result": growth.model_dump(mode="json"), "error": None,
        })
        if growth.value is None:
            gaps.append(f"{entity}: 同比不可计算({growth.non_computable_reason})")
            continue
        calc_refs.append(growth.calculation_id)
        pct = float(growth.value) * 100
        findings.append({
            "statement": (f"{entity} 截至 {current.period_end} 累计净利润 {current.value} 元,"
                          f"同比 {pct:+.2f}%({growth.calculation_id})"),
            "kind": "fact",
            "refs": [current.observation_id, base.observation_id, growth.calculation_id],
        })

    result = ResearchResult(
        objective=case.objective,
        researched_at=datetime.now(UTC).isoformat(),
        entity_ids=case.entity_ids,
        summary=";".join(f["statement"] for f in findings) or "固定流程未能产出结论",
        key_findings=findings or [{"statement": "数据不足,固定流程未产出结论", "kind": "fact", "refs": []}],
        metric_refs=metric_refs,
        calculation_refs=calc_refs,
        evidence_refs=[],
        information_gaps=gaps,
        skill_versions=[],
        tool_versions=["finance.get_metrics@1", "finance.calculate_growth@1"],
        quality_flags=[],
    )
    res.status = "succeeded"
    res.result = result.model_dump(mode="json")
    res.tool_outputs = outputs
    res.loaded_skills = []
    res.budget = {"max_model_calls": 0, "max_tool_calls": 0, "model_calls": 0, "tool_calls": len(outputs)}
    res.usage = {"input_tokens": 0, "output_tokens": 0}
    res.notes = "固定流程:无模型调用;不含公告检索与同业对齐"
    return res
