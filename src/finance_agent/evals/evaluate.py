"""评测编排:用例 × 分组顺序执行,落盘明细与报告。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from finance_agent.evals.cases import EvalCase, load_cases
from finance_agent.evals.report import aggregate, save_results
from finance_agent.evals.runner import run_case
from finance_agent.evals.scorers import score_case

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = PROJECT_ROOT / "evals" / "cases" / "dev"
DEFAULT_SKILLS = PROJECT_ROOT / "skills"


async def evaluate(
    *,
    groups: list[str],
    model,
    case_dir: Path = DEFAULT_CASES,
    skills_dir: Path = DEFAULT_SKILLS,
    out_dir: Path,
    user_overrides: dict | None = None,
    overrides_label: str | None = None,
    case_filter: list[str] | None = None,
) -> Path:
    cases: list[EvalCase] = [c for c in load_cases(case_dir)
                             if not case_filter or c.case_id in case_filter]
    pairs = []
    for case in cases:
        for group in groups:
            label = group if not (group == "C" and overrides_label) else overrides_label
            workspace = out_dir / "runs" / case.case_id / (label or group)
            cr = await run_case(
                case, group, model=model, workspace=workspace, skills_dir=skills_dir,
                user_overrides=user_overrides,
            )
            score = score_case(case, cr)
            score.group = label or group
            pairs.append((cr, score))
            print(f"[{label or group}] {case.case_id}: status={cr.status} "
                  f"completed={score.completed}", flush=True)

    meta = {
        "executed_at": datetime.now(UTC).isoformat(),
        "model": getattr(model, "model_name", type(model).__name__),
        "cases": str(case_dir),
        "case_count": len(cases),
        "groups": groups,
        "user_overrides": user_overrides,
        "overrides_label": overrides_label,
    }
    summary = aggregate([s for _, s in pairs])
    return save_results(out_dir, pairs, summary, meta)
