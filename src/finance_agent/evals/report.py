"""评测报告:逐题明细(JSON)与分组汇总(Markdown)。

样本量与随机性如实标注:每题每组单次运行;完成率是跨用例比例,
不代表分布结论(§16.2 要求关键样例重复运行——第一轮之后的改进项)。
"""

from __future__ import annotations

import json
from pathlib import Path

from finance_agent.evals.runner import CaseResult
from finance_agent.evals.scorers import CaseScore


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def aggregate(scores: list[CaseScore]) -> dict:
    by_group: dict[str, list[CaseScore]] = {}
    for s in scores:
        by_group.setdefault(s.group, []).append(s)
    summary = {}
    for group, items in sorted(by_group.items()):
        scored = [s for s in items if s.status != "not_applicable"]
        completed = sum(1 for s in scored if s.completed)
        citation_ok = sum(1 for s in scored if s.citation_valid)
        numeric_ok = sum(1 for s in scored if s.numeric_ok)
        skill_ok_items = [s for s in scored if s.group == "C"]
        summary[group] = {
            "cases": len(items),
            "scored": len(scored),
            "not_applicable": len(items) - len(scored),
            "completed": completed,
            "completion_rate": round(completed / len(scored), 4) if scored else None,
            "citation_valid_rate": round(citation_ok / len(scored), 4) if scored else None,
            "numeric_ok_rate": round(numeric_ok / len(scored), 4) if scored else None,
            "skill_ok_rate": (round(sum(1 for s in skill_ok_items if s.skill_ok) / len(skill_ok_items), 4)
                              if skill_ok_items else None),
            "time_violations": sum(s.time_violations for s in scored),
            "model_calls_total": sum(s.model_calls for s in scored),
            "tool_calls_total": sum(s.tool_calls for s in scored),
            "input_tokens_total": sum(s.input_tokens for s in scored),
            "output_tokens_total": sum(s.output_tokens for s in scored),
            "wall_p50": _pct([s.wall_seconds for s in scored], 0.5),
            "wall_p95": _pct([s.wall_seconds for s in scored], 0.95),
            "failures": [
                {
                    "case_id": s.case_id, "status": s.status,
                    "missing_refs": s.missing_refs, "missing_keywords": s.missing_keywords,
                    "missing_numbers": s.missing_numbers, "fabricated_numbers": s.fabricated_numbers,
                    "invalid_refs": s.invalid_refs, "skill_ok": s.skill_ok, "notes": s.notes,
                }
                for s in scored if not s.completed
            ],
        }
    return summary


def render_markdown(summary: dict, meta: dict) -> str:
    lines = [
        "# M4 评测报告(第一轮)", "",
        f"- 时间:{meta.get('executed_at', '')}",
        f"- 模型:{meta.get('model', '')}",
        f"- 用例集:{meta.get('cases', '')}({meta.get('case_count', 0)} 题)",
        "- 运行方式:每题每组单次运行;失败样例保留在分母(§16.2)",
        "- 评分覆盖:引用/数值/时间边界/完成标记为代码评分;语义支持度留待人工抽查",
        "",
        "| 分组 | 得分题数 | 完成率 | 引用有效 | 数值正确 | Skill选择* | 模型调用 | 工具调用 | 输入tok | 输出tok | P50(s) | P95(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group, g in summary.items():
        lines.append(
            f"| {group} | {g['scored']}/{g['cases']} | {g['completion_rate']} | "
            f"{g['citation_valid_rate']} | {g['numeric_ok_rate']} | {g['skill_ok_rate'] or '-'} | "
            f"{g['model_calls_total']} | {g['tool_calls_total']} | {g['input_tokens_total']} | "
            f"{g['output_tokens_total']} | {g['wall_p50']} | {g['wall_p95']} |"
        )
    lines += ["", "\\* Skill 选择合理率仅对 C 组且用例给出提示的题目计算。", ""]

    for group, g in summary.items():
        if g["failures"]:
            lines.append(f"## {group} 组失败样例")
            for f in g["failures"]:
                lines.append(f"- **{f['case_id']}**(status={f['status']})")
                for key in ("missing_refs", "missing_keywords", "missing_numbers",
                            "fabricated_numbers", "invalid_refs"):
                    if f[key]:
                        lines.append(f"  - {key}: {f[key]}")
                if not f["skill_ok"]:
                    lines.append("  - skill_ok: false")
                if f["notes"]:
                    lines.append(f"  - notes: {f['notes'][:200]}")
            lines.append("")
    return "\n".join(lines)


def save_results(out_dir: Path, pairs: list[tuple[CaseResult, CaseScore]], summary: dict, meta: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    detail = []
    for cr, s in pairs:
        detail.append({
            "case_result": {
                "case_id": cr.case_id, "group": cr.group, "status": cr.status,
                "result": cr.result, "loaded_skills": cr.loaded_skills,
                "budget": cr.budget, "usage": cr.usage,
                "wall_seconds": cr.wall_seconds, "error": cr.error, "notes": cr.notes,
            },
            "score": {
                "completed": s.completed, "partial": s.partial,
                "citation_valid": s.citation_valid, "invalid_refs": s.invalid_refs,
                "numeric_ok": s.numeric_ok, "missing_numbers": s.missing_numbers,
                "fabricated_numbers": s.fabricated_numbers,
                "missing_keywords": s.missing_keywords, "missing_refs": s.missing_refs,
                "skill_ok": s.skill_ok, "time_violations": s.time_violations,
                "model_calls": s.model_calls, "tool_calls": s.tool_calls,
                "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
                "wall_seconds": s.wall_seconds, "status": s.status, "notes": s.notes,
            },
        })
    (out_dir / "detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render_markdown(summary, meta)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    return out_dir / "report.md"
