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
from finance_agent.adapters.engines.deepagents.runner import (
    build_resume_payload,
    run_config,
    stream_run,
)
from finance_agent.adapters.engines.deepagents.tools import to_engine_tools
from finance_agent.adapters.persistence.repository import RunRepository
from finance_agent.application.result_validation import (
    build_run_trace,
    render_repair_feedback,
    validate_result,
)
from finance_agent.bootstrap import build_default_registry
from finance_agent.budget import Budget
from finance_agent.contracts.result import ResearchResult
from finance_agent.tools.registry import RecordingToolRegistry

ModelFactory = Callable[[dict], Any]
"""接收 run 行,返回本次尝试使用的模型。"""

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

    recorder = RecordingToolRegistry(build_default_registry())
    for prior in run.get("tool_trace") or []:
        recorder.outputs.append(prior)  # 跨 attempt 累积(§10.3 缓存语义)

    ctx_factory = make_ctx_factory(datetime.fromisoformat(run["as_of"]), budget.check_tool)
    engine_tools = to_engine_tools(bound_refs, recorder, ctx_factory)

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

    repair_phase = False  # 校验耗尽/修复轮失败 = 确定性失败,不走 requeue
    run_status_now = "running"

    async def persist_trace() -> None:
        await repo.save_tool_trace(run_id, fencing_token=fencing, outputs=recorder.outputs)

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

            payload = await build_resume_payload(agent, config, approve=run["resume_action"] == "approve")
            run_input = Command(resume=payload)
        else:
            run_input = None

        outcome = await stream_run(agent, run_input, config, budget,
                                   emit_event=emit_event, should_cancel=should_cancel)
        await repo.update_budget(run_id, fencing_token=fencing, budget_used=budget.snapshot())
        await persist_trace()
        run_status_now = "running"

        # ---- 结果校验链(§11 第 1–4 步)+ 修复循环(§6.2 第 7 步)----
        # 必须在 saver 块内:修复轮以新消息继续同一检查点会话
        if outcome.status == "succeeded" and outcome.result is not None:
            await repo.mark_validating(run_id, fencing_token=fencing)
            run_status_now = "validating"
            try:
                ResearchResult.model_validate(outcome.result)
            except Exception as e:  # noqa: BLE001 — 结构错误统一转失败并保留原因
                outcome.status, outcome.error = "failed", f"结果结构校验失败: {e}"
            else:
                max_rounds = int(limits.get("result_repair_rounds", 2))
                round_no = 0
                while True:
                    trace = build_run_trace(recorder.outputs, as_of=datetime.fromisoformat(run["as_of"]))
                    report = validate_result(outcome.result, trace)
                    await repo.add_event(
                        run_id, event_type="run.validating",
                        payload={"round": round_no, "hard": report.hard, "repairable": report.repairable},
                        attempt=attempt,
                    )
                    if report.ok:
                        break
                    if round_no >= max_rounds:
                        if report.hard:
                            outcome.status = "failed"
                            outcome.error = (
                                f"结果校验未通过(已用尽 {max_rounds} 轮修复):{'; '.join(report.hard[:3])}"
                            )
                        else:
                            # 资料不足但结构有效 → 部分结果待复核(§11 completed_partial)
                            outcome.status = "completed_partial"
                            outcome.result = {**outcome.result, "quality_flags": ["pending_review"]}
                        break
                    round_no += 1
                    repair_phase = True
                    await repo.add_event(
                        run_id, event_type="run.repair_feedback",
                        payload={"round": round_no, "issues": len(report.hard) + len(report.repairable)},
                        attempt=attempt,
                    )
                    await repo.mark_running(run_id, fencing_token=fencing)
                    run_status_now = "running"
                    outcome = await stream_run(
                        agent, {"messages": [("user", render_repair_feedback(report, round_no, max_rounds))]},
                        config, budget, emit_event=emit_event, should_cancel=should_cancel,
                    )
                    await repo.update_budget(run_id, fencing_token=fencing, budget_used=budget.snapshot())
                    await persist_trace()
                    if outcome.status == "succeeded" and outcome.result is not None:
                        try:
                            ResearchResult.model_validate(outcome.result)
                        except Exception as e:  # noqa: BLE001
                            outcome.status, outcome.error = "failed", f"修复轮结果结构校验失败: {e}"
                            break
                        continue
                    break  # 非成功结局交给统一终态处理

    if outcome.status == "waiting_approval":
        if run_status_now == "validating":
            await repo.mark_running(run_id, fencing_token=fencing)
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
        if repair_phase:
            # 校验耗尽/修复轮失败:确定性失败,重试对已完成的会话无意义
            ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                       attempt=attempt, error=outcome.error)
            return "failed" if ok else "lost_lease"
        if attempt < run["max_attempts"]:
            ok = await repo.requeue(run_id, fencing_token=fencing, error=outcome.error)
            return "requeued" if ok else "lost_lease"
        ok = await repo.finish_run(run_id, fencing_token=fencing, status="failed",
                                   attempt=attempt,
                                   error=f"已达最大尝试次数({run['max_attempts']}): {outcome.error}")
        return "failed" if ok else "lost_lease"

    if outcome.status in ("succeeded", "completed_partial"):
        # 结构有效(引用/数值问题已按轮次处理):终态 + 产物同事务提交
        ok = await repo.finish_run(
            run_id, fencing_token=fencing, status=outcome.status, attempt=attempt,
            result=outcome.result, artifact_kind="research-result.v1", artifact_content=outcome.result,
            error=outcome.error,
        )
        if not ok:
            return "lost_lease"
        await repo.add_event(
            run_id, event_type="run.skills_loaded",
            payload={"loaded": outcome.loaded_skills, "no_skill_selected": not outcome.loaded_skills},
            attempt=attempt,
        )
        return outcome.status
    raise AssertionError(f"未处理的执行结局: {outcome.status}")  # pragma: no cover


def default_model_factory(run: dict) -> Any:
    from finance_agent.adapters.models import build_chat_model

    return build_chat_model()
