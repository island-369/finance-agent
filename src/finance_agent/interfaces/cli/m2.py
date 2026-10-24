"""M2 CLI:Skill 发现、统一执行与执行记录查询。

用法:
    uv run m2 skills                                   # 列出 Skill 与可用性/依赖
    uv run m2 run --objective "..." [--skill name]     # 真实模型执行(需 .env)
    uv run m2 show <run_id>                            # 查看执行记录
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from finance_agent.application.run_service import (
    load_user_overrides,
    prepare_run,
    save_run_record,
)
from finance_agent.bootstrap import build_default_registry
from finance_agent.skills.resolver import SkillResolutionError

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNS_DIR = PROJECT_ROOT / "data" / "runtime" / "m2-runs"
DEFAULT_AS_OF = "2026-08-31T23:59:59+08:00"


def cmd_skills(args: argparse.Namespace) -> int:
    registry = build_default_registry()
    from finance_agent.skills.registry import scan_skill_dir
    from finance_agent.skills.resolver import resolve_skills

    records = scan_skill_dir(PROJECT_ROOT / "skills")
    overrides = load_user_overrides(Path(args.user_overrides)) if args.user_overrides else None
    resolved = resolve_skills(records, registry, user_overrides=overrides)
    rows = [
        {
            "ref": r.ref,
            "available": r.available,
            "reason": r.reason,
            "degraded_tools": list(r.degraded_tools),
            "description": r.record.description,
        }
        for r in resolved
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


async def _execute(args: argparse.Namespace, model) -> int:
    from finance_agent.adapters.engines.deepagents.agent import (
        build_research_agent,
        make_ctx_factory,
    )
    from finance_agent.adapters.engines.deepagents.runner import run_config, stream_run
    from finance_agent.adapters.engines.deepagents.tools import to_engine_tools
    from finance_agent.budget import Budget

    registry = build_default_registry()
    overrides = load_user_overrides(Path(args.user_overrides)) if args.user_overrides else None
    prefs = [args.skill] if args.skill else None
    try:
        plan = prepare_run(
            objective=args.objective,
            entity_ids=args.entities,
            as_of=args.as_of,
            tool_registry=registry,
            user_overrides=overrides,
            task_preferences=prefs,
            runtime_dir=RUNS_DIR.parent,
        )
    except (SkillResolutionError, FileNotFoundError, ValueError) as e:
        # 显式指定无法满足/元数据非法:任务创建即失败,不静默替换
        print(f"任务创建失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    budget = Budget(max_model_calls=args.max_model_calls, max_tool_calls=args.max_tool_calls)
    ctx_factory = make_ctx_factory(datetime.fromisoformat(args.as_of), budget.check_tool)
    engine_tools = to_engine_tools(plan.bound_tool_refs, registry, ctx_factory)

    from finance_agent.adapters.engines.deepagents.checkpoints import open_sqlite_saver

    ckpt = RUNS_DIR / plan.run_id / "checkpoints.sqlite"
    async with open_sqlite_saver(ckpt) as saver:
        agent = build_research_agent(
            model, skills_view_root=plan.view_root, engine_tools=engine_tools, checkpointer=saver
        )
        objective_text = (
            f"{args.objective}\n涉及公司: {', '.join(args.entities)}\n"
            f"任务截止时间(as_of): {args.as_of}"
        )
        config = run_config(plan.run_id)
        outcome = await stream_run(agent, {"messages": [("user", objective_text)]}, config, budget)

    model_desc = {"provider": "openai-compatible", "model": getattr(model, "model_name", type(model).__name__)}
    record_path = save_run_record(plan, outcome, model_desc)
    summary = {
        "run_id": plan.run_id,
        "status": outcome.status,
        "candidates": [r.ref for r in plan.candidates],
        "bound_tools": [f"{n}@{m}" for n, m in plan.bound_tool_refs],
        "loaded_skills": outcome.loaded_skills,
        "no_skill_selected": not outcome.loaded_skills,
        "budget": outcome.budget,
        "usage": outcome.usage,
        "record": str(record_path),
        "error": outcome.error,
        "summary": (outcome.result or {}).get("summary"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if outcome.status in ("succeeded", "waiting_approval") else 1


def cmd_run(args: argparse.Namespace) -> int:
    from finance_agent.adapters.models import MissingApiKeyError, build_chat_model

    try:
        model = build_chat_model()
    except MissingApiKeyError as e:
        print(f"{e}", file=sys.stderr)
        return 2
    return asyncio.run(_execute(args, model))


def cmd_show(args: argparse.Namespace) -> int:
    path = RUNS_DIR / args.run_id / "record.json"
    if not path.is_file():
        print(f"找不到执行记录: {path}", file=sys.stderr)
        return 2
    print(path.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m2", description="M2 Skill 注册与统一执行 CLI")
    parser.add_argument("--user-overrides", default=None, help="用户 Skill 覆盖 JSON(name→version)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_skills = sub.add_parser("skills", help="列出 Skill 与可用性")
    p_skills.set_defaults(func=cmd_skills)

    p_run = sub.add_parser("run", help="执行一次研究任务(真实模型)")
    p_run.add_argument("--objective", required=True)
    p_run.add_argument("--entities", nargs="+", required=True)
    p_run.add_argument("--as-of", default=DEFAULT_AS_OF)
    p_run.add_argument("--skill", default=None, help="显式指定 Skill(name 或 name@version)")
    p_run.add_argument("--max-model-calls", type=int, default=15)
    p_run.add_argument("--max-tool-calls", type=int, default=30)
    p_run.set_defaults(func=cmd_run)

    p_show = sub.add_parser("show", help="查看执行记录")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
