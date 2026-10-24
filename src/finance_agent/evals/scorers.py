"""评分器(设计 §16.3 的代码可评子集)。

- 引用有效率:结果引用的 obs-/chk- ID 必须出现在本次运行的工具输出中且
  available_at ≤ as_of;calc- 引用必须对应本次工具返回的计算。
- 数值准确率:期望数值的任一文本表示出现在结果文本中。
- 任务完成率:状态 succeeded + 必需引用齐备 + 必需关键词命中;部分满足
  记 completed_partial_requirements。
- 时间边界违规:工具输出中出现 available_at > as_of 的观测(结构性应为 0)。
- 选择合理率(仅 C 组):加载了 skill_hint 中任一 Skill,或 allow_no_skill。
- 成本与耗时:模型/工具调用数、token、墙钟时间(P50/P95 在报告层汇总)。

语义支持度(结论是否真被证据支撑)不在代码评分范围,报告如实标注
留待人工抽查(§16.3)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from finance_agent.evals.cases import EvalCase
from finance_agent.evals.runner import CaseResult


@dataclass
class CaseScore:
    case_id: str
    group: str
    task_type: str
    status: str
    completed: bool = False
    partial: bool = False
    citation_valid: bool = True
    invalid_refs: list[str] = field(default_factory=list)
    numeric_ok: bool = True
    missing_numbers: list[str] = field(default_factory=list)
    fabricated_numbers: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    missing_refs: list[str] = field(default_factory=list)
    skill_ok: bool = True
    time_violations: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    notes: str = ""


def _result_text(result: dict | None) -> str:
    if not result:
        return ""
    parts = [result.get("summary") or ""]
    for f in result.get("key_findings") or []:
        parts.append(f.get("statement") or "")
    parts.extend(result.get("information_gaps") or [])
    parts.extend(result.get("assumptions") or [])
    return " ".join(parts)


def _valid_ids(tool_outputs: list[dict], as_of: datetime) -> set[str]:
    valid: set[str] = set()
    iso = as_of.isoformat()
    for out in tool_outputs:
        payload = out.get("result") or {}
        for obs in (payload.get("observations") or []):
            if obs.get("available_at", "9999") <= iso:
                valid.add(obs["observation_id"])
        for hit in ((payload.get("hits") or []) if isinstance(payload, dict) else []):
            ev = hit.get("evidence") or {}
            if ev.get("available_at", "9999") <= iso:
                valid.add(ev.get("evidence_id"))
            # 文档版本 ID 同为合法证据引用(M4 报告 §3 归一化改进):
            # 引用 docv-* 与引用其下 chk-* 等价,均指向本次工具输出中出现过的版本
            doc = hit.get("document") or {}
            if doc.get("available_at", "9999") <= iso:
                valid.add(doc.get("version_id"))
        # compare_peers 行内 observation_id
        for row in (payload.get("rows") or []):
            if row.get("observation_id"):
                valid.add(row["observation_id"])
        if out["tool"] == "finance.calculate_growth" and out["ok"]:
            valid.add(payload["calculation_id"])
    return valid


def _all_refs(result: dict | None) -> list[str]:
    if not result:
        return []
    refs = list(result.get("metric_refs") or [])
    refs += list(result.get("calculation_refs") or [])
    refs += [e.get("evidence_id") for e in (result.get("evidence_refs") or [])]
    for f in result.get("key_findings") or []:
        refs += f.get("refs") or []
    return [r for r in refs if r]


def score_case(case: EvalCase, cr: CaseResult) -> CaseScore:
    s = CaseScore(
        case_id=case.case_id, group=cr.group, task_type=case.task_type, status=cr.status,
        model_calls=cr.budget.get("model_calls", 0),
        tool_calls=cr.budget.get("tool_calls", 0),
        input_tokens=cr.usage.get("input_tokens", 0),
        output_tokens=cr.usage.get("output_tokens", 0),
        wall_seconds=round(cr.wall_seconds, 2),
        notes=cr.notes or (cr.error or ""),
    )
    if cr.status == "not_applicable":
        return s

    as_of = datetime.fromisoformat(case.as_of)
    valid = _valid_ids(cr.tool_outputs, as_of)

    # 引用有效率
    refs = _all_refs(cr.result)
    s.invalid_refs = sorted({r for r in refs if r not in valid})
    s.citation_valid = not s.invalid_refs

    # 时间边界违规(结构性检查)
    for out in cr.tool_outputs:
        payload = out.get("result") or {}
        for obs in (payload.get("observations") or []):
            if obs.get("available_at", "") > as_of.isoformat():
                s.time_violations += 1

    text = _result_text(cr.result)
    exp = case.expectation

    # 数值与关键词
    s.missing_numbers = [n for n in exp.expected_numbers if n not in text]
    s.fabricated_numbers = [n for n in exp.forbidden_numbers if n in text]
    # 期望数值“任一命中即通过”;禁用数值必须全部缺席
    s.numeric_ok = (
        (not exp.expected_numbers or len(exp.expected_numbers) > len(s.missing_numbers))
        and not s.fabricated_numbers
    )
    s.missing_keywords = [k for k in exp.required_keywords if k not in text]

    # 必需引用
    s.missing_refs = [r for r in exp.required_refs if r not in refs]

    # Skill 选择合理率(C 组且给了提示)
    if cr.group == "C" and exp.skill_hint:
        s.skill_ok = bool(set(cr.loaded_skills) & set(exp.skill_hint)) or (
            not cr.loaded_skills and exp.allow_no_skill
        )

    ok_status = cr.status == "succeeded"
    hard = s.citation_valid and not s.missing_refs and not s.missing_keywords
    s.completed = ok_status and hard and s.numeric_ok and s.skill_ok
    s.partial = ok_status and hard and not s.completed
    return s
