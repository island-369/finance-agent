"""M0 CLI:离线兼容性检查、真实模型执行、检查点恢复。

用法:
    uv run m0 check                                   # 无需模型秘钥的离线检查
    uv run m0 run [--objective ...] [--as-of ...]     # 真实模型执行(需要 .env)
    uv run m0 run --interrupt-on-tool finance_get_metrics   # 演示审批中断
    uv run m0 resume --thread <id> [--reject]         # 恢复中断的任务
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from finance_agent.m0.budget import Budget
from finance_agent.m0.runner import (
    RunOutcome,
    build_resume_payload,
    resume_payload,
    stream_run,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS = PROJECT_ROOT / "skills"
DEFAULT_RUNTIME = PROJECT_ROOT / "data" / "runtime"
DEFAULT_AS_OF = "2026-08-31T23:59:59+08:00"
DEFAULT_OBJECTIVE = (
    "分析 demo-company-a 2026 年上半年净利润变化,"
    "识别与收入变化不一致的环节并给出证据"
)


def _runtime_dir(args: argparse.Namespace) -> Path:
    d = Path(getattr(args, "runtime_dir", None) or DEFAULT_RUNTIME)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _emit_ndjson(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _print_outcome(outcome: RunOutcome, thread: str) -> None:
    summary = {
        "thread": thread,
        "status": outcome.status,
        "budget": outcome.budget,
        "usage": outcome.usage,
        "events": len(outcome.events),
    }
    if outcome.error:
        summary["error"] = outcome.error
    if outcome.result:
        summary["result"] = outcome.result
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if outcome.status == "waiting_approval":
        print(f"任务等待审批。恢复: uv run m0 resume --thread {thread}", file=sys.stderr)


# ---------------------------------------------------------------- check ----


async def cmd_check(args: argparse.Namespace) -> int:
    """离线兼容性检查:全部使用确定性假模型,不需要模型秘钥。"""
    from langchain_core.messages import AIMessage
    from langgraph.types import Command

    from finance_agent.m0.agent import build_agent
    from finance_agent.m0.checkpoints import open_sqlite_saver
    from finance_agent.m0.fixtures import DEFAULT_OBSERVATIONS
    from finance_agent.m0.skills_view import build_skill_view
    from finance_agent.m0.testing import ScriptedChatModel
    from finance_agent.m0.tools import (
        BUDGET_EXCEEDED,
        TIME_BOUNDARY_VIOLATION,
        make_finance_get_metrics_tool,
    )

    runtime = _runtime_dir(args)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    # 1. Skill 只读视图构建(版本选择 + manifest 哈希)
    view_root = runtime / "skills-view"
    manifest = build_skill_view(REPO_SKILLS, view_root)
    ok = len(manifest) == 1 and manifest[0]["name"] == "earnings-analysis" and len(manifest[0]["skill_md_sha256"]) == 64
    check("skill-view: 版本化目录展开为扁平视图并生成内容哈希", ok, json.dumps(manifest, ensure_ascii=False))

    task_as_of = datetime.fromisoformat(DEFAULT_AS_OF)

    # 2. 工具时间边界与修订版本选择(直接调用,不经模型)
    tool = make_finance_get_metrics_tool(DEFAULT_OBSERVATIONS, Budget(), task_as_of)
    late = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit", "as_of": "2026-12-31T00:00:00+08:00"}))
    check(
        "tool: as_of 晚于任务截止时间被拒绝",
        late.get("error", {}).get("code") == TIME_BOUNDARY_VIOLATION,
        str(late.get("error", {}).get("code")),
    )
    before_revision = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit", "as_of": "2026-05-01T00:00:00+08:00"}))
    after_revision = json.loads(tool.invoke({"entity_id": "demo-company-a", "metric": "net_profit"}))
    v1 = [o for o in before_revision["observations"] if o["period_end"] == "2026-03-31"]
    v2 = [o for o in after_revision["observations"] if o["period_end"] == "2026-03-31"]
    check(
        "tool: 修订版本按截止时间选择(05-01 取 v1 / 08-31 取 v2)",
        v1 and v2 and v1[0]["revision_id"] == "v1" and v1[0]["value"] == "112000000.00"
        and v2[0]["revision_id"] == "v2" and v2[0]["value"] == "98000000.00",
        f"v1={v1[0]['value'] if v1 else None} v2={v2[0]['value'] if v2 else None}",
    )
    exhausted = make_finance_get_metrics_tool(
        DEFAULT_OBSERVATIONS, Budget(max_tool_calls=0), task_as_of
    )
    resp = json.loads(exhausted.invoke({"entity_id": "demo-company-a", "metric": "revenue"}))
    check(
        "tool: 预算耗尽返回结构化错误而非异常",
        resp.get("error", {}).get("code") == BUDGET_EXCEEDED,
        str(resp.get("error", {}).get("code")),
    )

    # 3. 端到端假模型执行:Skill 读取 + 工具调用 + 结构化结果 + 事件 + 预算
    final_args = {
        "objective": "分析 demo-company-a 2026 年上半年净利润变化",
        "summary": "2026H1 净利润(修订口径)2.72 亿元;Q2 利润率环比下滑。",
        "key_findings": [
            "2026Q1 净利润 98,000,000 元(修订版 v2,obs-013)",
            "2026Q2 净利润 174,000,000 元(obs-012),单季利润率 6.0%,低于 Q1 的 7.0%",
        ],
        "metric_refs": ["obs-013", "obs-012"],
        "evidence_refs": ["/skills/earnings-analysis/SKILL.md"],
        "assumptions": [],
        "information_gaps": ["缺少成本科目明细,无法定位利润率下滑的具体科目"],
    }

    def scripted_messages() -> list:
        return [
            AIMessage(
                content="",
                tool_calls=[{"name": "finance_get_metrics", "args": {"entity_id": "demo-company-a", "metric": "net_profit"}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"file_path": "/skills/earnings-analysis/SKILL.md"}, "id": "c2", "type": "tool_call"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "M0ResearchResult", "args": final_args, "id": "c3", "type": "tool_call"}],
            ),
        ]

    def scripted_model_from(messages: list, i: int = 0) -> ScriptedChatModel:
        # 真实模型恢复时对话历史来自检查点;脚本模型需显式指定起始位置
        m = ScriptedChatModel(responses=messages)
        m.i = i
        return m

    ckpt = runtime / "m0-check.sqlite"
    if ckpt.exists():
        ckpt.unlink()

    async with open_sqlite_saver(ckpt) as saver:
        budget = Budget(max_model_calls=6, max_tool_calls=6)
        model = scripted_model_from(scripted_messages(), 0)
        agent = build_agent(model, skills_view_root=view_root, budget=budget, task_as_of=task_as_of, checkpointer=saver)
        config = {"configurable": {"thread_id": "check-e2e"}}
        outcome = await stream_run(agent, {"messages": [("user", DEFAULT_OBJECTIVE)]}, config, budget)

        tool_names = [e["name"] for e in outcome.events if e["type"] == "tool_start"]
        check(
            "e2e: 状态 succeeded 且结构化结果通过 ToolStrategy 解析",
            outcome.status == "succeeded" and outcome.result == final_args,
            outcome.status,
        )
        check(
            "e2e: 事件流覆盖模型调用/工具调用,含 read_file 读取 Skill 正文",
            "finance_get_metrics" in tool_names and "read_file" in tool_names,
            ",".join(tool_names),
        )
        check(
            "e2e: 预算计数(3 次模型调用,2 次工具调用)",
            budget.model_calls == 3 and budget.tool_calls == 2,
            f"model={budget.model_calls} tool={budget.tool_calls}",
        )

    # 4. 审批中断 + 跨连接恢复(两段独立打开检查点文件,模拟 Worker 重启)
    if ckpt.exists():
        ckpt.unlink()
    budget2 = Budget(max_model_calls=6, max_tool_calls=6)
    config2 = {"configurable": {"thread_id": "check-hitl"}}
    interrupt_on = {"finance_get_metrics": True}
    script = scripted_messages()

    async with open_sqlite_saver(ckpt) as saver:
        agent1 = build_agent(
            scripted_model_from(script, 0), skills_view_root=view_root, budget=budget2,
            task_as_of=task_as_of, checkpointer=saver, interrupt_on=interrupt_on,
        )
        out1 = await stream_run(agent1, {"messages": [("user", DEFAULT_OBJECTIVE)]}, config2, budget2)
    check("hitl: 工具审批中断,状态 waiting_approval", out1.status == "waiting_approval", out1.status)

    # 新连接、新模型实例(对话历史来自检查点;脚本模型需显式从第 2 条继续)
    async with open_sqlite_saver(ckpt) as saver:
        agent2 = build_agent(
            scripted_model_from(script, 1), skills_view_root=view_root, budget=budget2,
            task_as_of=task_as_of, checkpointer=saver, interrupt_on=interrupt_on,
        )
        out2 = await stream_run(agent2, Command(resume=resume_payload(approve=True)), config2, budget2)
    check(
        "hitl: 新连接恢复后完成,结果一致,预算沿同一计数器累计",
        out2.status == "succeeded" and out2.result == final_args
        and budget2.model_calls == 3 and budget2.tool_calls == 2,
        f"status={out2.status} model={budget2.model_calls} tool={budget2.tool_calls}",
    )

    # 5. 模型调用预算越界:第 2 次调用计数后中止,状态明确
    budget_ckpt = runtime / "m0-budget.sqlite"
    if budget_ckpt.exists():
        budget_ckpt.unlink()
    async with open_sqlite_saver(budget_ckpt) as saver:
        budget3 = Budget(max_model_calls=2, max_tool_calls=6)
        agent3 = build_agent(
            scripted_model_from(script, 0), skills_view_root=view_root, budget=budget3,
            task_as_of=task_as_of, checkpointer=saver,
        )
        config3 = {"configurable": {"thread_id": "check-budget"}}
        out3 = await stream_run(agent3, {"messages": [("user", DEFAULT_OBJECTIVE)]}, config3, budget3)
    check(
        "budget: 模型调用越界后中止,状态 budget_exceeded",
        out3.status == "budget_exceeded" and budget3.model_calls == 2,
        f"status={out3.status} model={budget3.model_calls}",
    )

    failed = [r for r in results if not r[1]]
    print(
        f"\n离线兼容性检查:{len(results) - len(failed)}/{len(results)} 通过"
        + ("" if not failed else ";失败项:" + ", ".join(r[0] for r in failed)),
        flush=True,
    )
    return 0 if not failed else 1


# ----------------------------------------------------------------- run -----


async def cmd_run(args: argparse.Namespace) -> int:
    from finance_agent.m0.agent import build_agent
    from finance_agent.m0.checkpoints import open_sqlite_saver
    from finance_agent.m0.model import build_chat_model
    from finance_agent.m0.skills_view import build_skill_view

    runtime = _runtime_dir(args)
    build_skill_view(REPO_SKILLS, runtime / "skills-view")
    model = build_chat_model()  # 缺秘钥时在这里给出明确报错
    as_of = datetime.fromisoformat(args.as_of)
    thread = args.thread or uuid.uuid4().hex[:12]

    run_meta = {
        "objective": args.objective,
        "as_of": args.as_of,
        "thread": thread,
        "engine": "deepagents",
        "interrupt_on_tool": args.interrupt_on_tool,
    }
    meta_path = runtime / f"run-{thread}.json"
    meta_path.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    budget = Budget(
        max_model_calls=args.max_model_calls,
        max_tool_calls=args.max_tool_calls,
    )
    interrupt_on = {args.interrupt_on_tool: True} if args.interrupt_on_tool else None

    async with open_sqlite_saver(runtime / "m0-checkpoints.sqlite") as saver:
        agent = build_agent(
            model,
            skills_view_root=runtime / "skills-view",
            budget=budget,
            task_as_of=as_of,
            checkpointer=saver,
            interrupt_on=interrupt_on,
        )
        config = {"configurable": {"thread_id": thread}}
        outcome = await stream_run(
            agent,
            {"messages": [("user", args.objective)]},
            config,
            budget,
            emit=_emit_ndjson,
        )
    _print_outcome(outcome, thread)
    return 0 if outcome.status in ("succeeded", "waiting_approval") else 1


async def cmd_resume(args: argparse.Namespace) -> int:
    from langgraph.types import Command

    from finance_agent.m0.agent import build_agent
    from finance_agent.m0.checkpoints import open_sqlite_saver
    from finance_agent.m0.model import build_chat_model
    from finance_agent.m0.skills_view import build_skill_view

    runtime = _runtime_dir(args)
    meta_path = runtime / f"run-{args.thread}.json"
    if not meta_path.exists():
        print(f"找不到任务记录 {meta_path}", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    build_skill_view(REPO_SKILLS, runtime / "skills-view")
    model = build_chat_model()
    # M0 已知缺口:恢复时预算从零计数(设计要求沿用已消耗计数),M3 任务表解决
    budget = Budget(max_model_calls=args.max_model_calls, max_tool_calls=args.max_tool_calls)

    async with open_sqlite_saver(runtime / "m0-checkpoints.sqlite") as saver:
        agent = build_agent(
            model,
            skills_view_root=runtime / "skills-view",
            budget=budget,
            task_as_of=datetime.fromisoformat(meta["as_of"]),
            checkpointer=saver,
            interrupt_on={meta["interrupt_on_tool"]: True} if meta.get("interrupt_on_tool") else None,
        )
        config = {"configurable": {"thread_id": args.thread}}
        payload = await build_resume_payload(
            agent, config, approve=not args.reject, message=args.message or None
        )
        outcome = await stream_run(
            agent,
            Command(resume=payload),
            config,
            budget,
            emit=_emit_ndjson,
        )
    _print_outcome(outcome, args.thread)
    return 0 if outcome.status == "succeeded" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m0", description="M0 底座兼容实验 CLI")
    parser.add_argument("--runtime-dir", default=None, help="运行时目录(默认 data/runtime)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="离线兼容性检查(不需要模型秘钥)")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="真实模型执行一次研究任务")
    p_run.add_argument("--objective", default=DEFAULT_OBJECTIVE)
    p_run.add_argument("--as-of", default=DEFAULT_AS_OF)
    p_run.add_argument("--thread", default=None, help="thread_id(默认随机);恢复时需一致")
    p_run.add_argument("--interrupt-on-tool", default=None, metavar="TOOL", help="在指定工具前中断等待审批,如 finance_get_metrics")
    p_run.add_argument("--max-model-calls", type=int, default=15)
    p_run.add_argument("--max-tool-calls", type=int, default=30)
    p_run.set_defaults(func=cmd_run)

    p_resume = sub.add_parser("resume", help="恢复等待审批的任务")
    p_resume.add_argument("--thread", required=True)
    p_resume.add_argument("--reject", action="store_true", help="拒绝而非批准(默认批准)")
    p_resume.add_argument("--message", default=None, help="拒绝/批准附言")
    p_resume.add_argument("--max-model-calls", type=int, default=15)
    p_resume.add_argument("--max-tool-calls", type=int, default=30)
    p_resume.set_defaults(func=cmd_resume)

    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
