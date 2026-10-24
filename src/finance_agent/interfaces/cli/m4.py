"""M4 评测 CLI。

用法:
    uv run m4 check                      # 离线:用例校验 + D 管道 + 评分器自检
    uv run m4 eval --groups A,B,C,D      # 真实模型评测(需 .env)
    uv run m4 eval --groups C --old-skill --case-filter ea-1 ea-2 ea-3 \
                   --label C-old         # Skill 新旧版本比较
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from finance_agent.evals.cases import load_cases
from finance_agent.evals.evaluate import DEFAULT_CASES, evaluate

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT = PROJECT_ROOT / "evals" / "results"


def cmd_check(args: argparse.Namespace) -> int:
    """离线检查:用例可加载、D 管道在 earnings 用例上可产出、评分器可判。"""
    from finance_agent.evals.pipeline_d import run_pipeline_d
    from finance_agent.evals.scorers import score_case

    cases = load_cases(Path(args.cases))
    print(f"用例加载 OK:{len(cases)} 题")
    earnings = [c for c in cases if c.task_type == "earnings"]
    ok = True
    for c in earnings:
        cr = run_pipeline_d(c)
        s = score_case(c, cr)
        print(f"[D] {c.case_id}: status={cr.status} completed={s.completed} refs={s.missing_refs}")
        ok = ok and cr.status == "succeeded"
    print("离线检查:" + ("通过" if ok else "失败"))
    return 0 if ok else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from finance_agent.adapters.models import build_chat_model

    model = build_chat_model()
    overrides = None
    if args.old_skill:
        overrides = {"earnings-analysis": args.old_skill}
    out_dir = args.out or (DEFAULT_OUT / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
                           + (f"-{args.label}" if args.label else ""))
    groups = args.groups.split(",")
    asyncio.run(evaluate(
        groups=groups, model=model,
        case_dir=Path(args.cases),
        out_dir=Path(out_dir),
        user_overrides=overrides,
        overrides_label=args.label,
        case_filter=args.case_filter,
    ))
    print(f"报告: {Path(out_dir) / 'report.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m4", description="M4 评测 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="离线自检")
    p_check.add_argument("--cases", default=str(DEFAULT_CASES))
    p_check.set_defaults(func=cmd_check)

    p_eval = sub.add_parser("eval", help="真实模型评测")
    p_eval.add_argument("--groups", default="A,B,C,D")
    p_eval.add_argument("--cases", default=str(DEFAULT_CASES))
    p_eval.add_argument("--out", default=None)
    p_eval.add_argument("--label", default=None, help="配置标签(如 C-old)")
    p_eval.add_argument("--old-skill", default="0.1.0", help="新旧比较:覆盖 earnings-analysis 到该版本")
    p_eval.add_argument("--case-filter", nargs="*", default=None)
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
