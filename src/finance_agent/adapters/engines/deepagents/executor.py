"""任务执行器:把 runs 表的一行交给引擎执行,并落库事件/预算/终态。

对应设计 §6.2、§10:
- 事件逐条 await 写入 run_events(实时可 SSE 补读),预算随事件更新(§10.4)。
- 取消:模型/工具调用前检查 cancel_requested_at(§6.3)。
- 恢复:attempt > 1 时以 None 输入从引擎检查点续跑(已完成的工具调用
  不重复执行);HITL 等待审批的任务按 resume_action 以 Command(resume=...)
  恢复,决定数量从检查点挂起调用数推导(M0 结论)。
- 崩溃:执行异常且 attempt < max_attempts 时 requeue(保留检查点与预算),
  否则 failed 并保留真实错误(不可恢复场景有真实错误说明)。
- 模型工厂可注入(测试按 attempt 提供脚本模型;生产默认 OpenAI 兼容端点)。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from finance_agent.adapters.engines.deepagents.agent import (
    build_research_agent,
    make_ctx_factory,
)
from finance_agent.adapters.engines.deepagents.checkpoints import open_sqlite_saver
from finance_agent.adapters.engines.deepagents.runner import run_config, stream_run
from finance_agent.adapters.engines.deepagents.tools import to_engine_tools
from finance_agent.adapters.persistence.repository import RunRepository
from finance_agent.bootstrap import build_default_registry
from finance_agent.budget import Budget
from finance_agent.contracts.result import ResearchResult

ModelFactory = Callable[[dict], Any]
"""接收 run 行,返回本次尝试使用的模型。"""

TOOL_REF_FIXUPS = {"documents_search": "documents.search"}


def _parse_bound_refs(refs: list[str]) -> list[tuple[str, int]]:
    parsed: list[tuple[str, int]] = []
    for ref in refs:
        name, _, major = ref.rpartition("@")
        parsed.append((name, int(major)))
    return parsed


def _objective_text(objective: str, entity_ids: list, as_of: str) -> str:
    return f"{objective}\n涉及公司: {', '.join(entity_ids)}\n任务截止时间(as_of): {as_of}"


async def execute_run(
    run: dict,
    repo: RunRepository,
    *,
    runtime_dir: Path,
    model_factory: ModelFactory,
) -> str:
    """执行一个已领取的 run;返回最终状态字符串(lost_lease 表示租约已丢失)。"""
    run_id = run["id"]
    fencing = run["fencing_token"]
    attempt = run["attempt"]
    limits = run.get("budget_limits") or {}

    budget = Budget(
        max_model_calls=limits.get("max_model_calls", 15),
        max_tool_calls=limits.get("max_tool_calls", 30),
    )
    used = run.get("budget_used") or {}
    if used:  # §10.4:恢复沿用已消耗计数
        budget.model_calls = used.get("model_calls", 0)
        budget.tool_calls = used.get("tool_calls", 0)

    config_snapshot = run.get("config") or {}
    view_root = Path(config_snapshot["view_root"])
    bound_refs = _parse_bound_refs(config_snapshot["bound_tools"])

    tool_registry = build_default_registry()
    ctx_factory = make_ctx_factory(datetime.fromisoformat(run["as_of"]), budget.check_tool)
    engine_tools = to_engine_tools(bound_refs, tool_registry, ctx_factory)

    ckpt_path = runtime_dir / "checkpoints" / f"{run_id}.sqlite"

    await repo.add_event(
        run_id,
        event_type="run.attempt_started",
        payload={"attempt": attempt, "resume_action": run.get("resume_action"),
                 "budget_carried": budget.snapshot()},
        attempt=attempt,
    )

    try:
        model = model_factory(run)
    except Exception as e:  # noqa: BLE001 — 模型装配失败属于不可恢复配置问题,任何异常都要转为任务失败
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                   attempt=attempt, error=f"模型装配失败: {type(e).__name__}: {e}")
        return "failed" if ok else "lost_lease"

    async def emit_event(event: dict) -> None:
        payload = {k: v for k, v in event.items() if k != "seq"}
        await repo.add_event(run_id, event_type=f"engine.{event['type']}", payload=payload, attempt=attempt)
        await repo.update_budget(run_id, fencing_token=fencing, budget_used=budget.snapshot())

    async def should_cancel() -> bool:
        return await repo.is_cancel_requested(run_id)

    async with open_sqlite_saver(ckpt_path) as saver:
        agent = build_research_agent(
            model, skills_view_root=view_root, engine_tools=engine_tools, checkpointer=saver,
            interrupt_on=config_snapshot.get("interrupt_on") or None,
        )
        config = run_config(run_id)

        # 输入选择:首跑正常输入;审批恢复 Command(resume);崩溃恢复 None 续跑
        if attempt == 1 and not run.get("resume_action"):
            run_input: Any = {"messages": [("user", _objective_text(run["objective"], run["entity_ids"], run["as_of"]))]}
        elif run.get("resume_action"):
            from langgraph.types import Command

            from finance_agent.m0.runner import build_resume_payload

            payload = await build_resume_payload(agent, config, approve=run["resume_action"] == "approve")
            run_input = Command(resume=payload)
        else:
            run_input = None

        outcome = await stream_run(agent, run_input, config, budget,
                                   emit_event=emit_event, should_cancel=should_cancel)

    await repo.update_budget(run_id, fencing_token=fencing, budget_used=budget.snapshot())

    if outcome.status == "waiting_approval":
        ok = await repo.mark_waiting_input(run_id, fencing_token=fencing, attempt=attempt,
                                           note="工具调用等待审批(可 POST /resume 恢复)")
        return "waiting_input" if ok else "lost_lease"

    if outcome.status == "cancelled":
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="cancelled",
                                   attempt=attempt, error=outcome.error)
        return "cancelled" if ok else "lost_lease"

    if outcome.status == "budget_exceeded":
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                   attempt=attempt, error=f"预算越界: {outcome.error}")
        return "failed" if ok else "lost_lease"

    if outcome.status == "failed":
        if attempt < run["max_attempts"]:
            ok = await repo.requeue(run_id, fencing_token=fencing, error=outcome.error)
            return "requeued" if ok else "lost_lease"
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                   attempt=attempt,
                                   error=f"已达最大尝试次数({run['max_attempts']}): {outcome.error}")
        return "failed" if ok else "lost_lease"

    # succeeded:结构校验(§11 第 1 步雏形)→ 终态 + 产物同事务提交
    await repo.mark_validating(run_id, fencing_token=fencing)
    try:
        ResearchResult.model_validate(outcome.result or {})
    except Exception as e:  # noqa: BLE001 — 校验错误统一转为任务失败并保留原因
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                   attempt=attempt, error=f"结果结构校验失败: {e}")
        return "failed" if ok else "lost_lease"

    ok = await repo.finish_run(
        run_id, fencing_token=fencing, status="succeeded", attempt=attempt,
        result=outcome.result, artifact_kind="research-result.v1", artifact_content=outcome.result,
    )
    if not ok:
        return "lost_lease"
    await repo.add_event(
        run_id, event_type="run.skills_loaded",
        payload={"loaded": outcome.loaded_skills, "no_skill_selected": not outcome.loaded_skills},
        attempt=attempt,
    )
    return "succeeded"


def default_model_factory(run: dict) -> Any:
    from finance_agent.m0.model import build_chat_model

    return build_chat_model()
