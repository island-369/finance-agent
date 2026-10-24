"""M0 执行器:事件流、预算计数、结果与中断提取。

对应设计 §6.2 步骤 4–7 的雏形:消费引擎事件 → 归一化为公开事件 →
预算越界时放弃执行 → 从图状态提取候选结果或等待审批状态。

事件归一化只保留公开可观察信息(类型、名称、用量、简短输入摘要),
不依赖模型内部思维过程(§13.3)。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from finance_agent.adapters.engines.deepagents.runner import (
    build_resume_payload,
    resume_payload,
)
from finance_agent.m0.budget import Budget, BudgetAbort

__all__ = ["RunOutcome", "build_resume_payload", "resume_payload", "stream_run"]

EmitFn = Callable[[dict], None]

# 只把这几类引擎事件映射为公开事件;其余(内部 chain 细节)不外发
_EVENT_MAP = {
    "on_chat_model_start": "model_call_start",
    "on_chat_model_end": "model_call_end",
    "on_tool_start": "tool_start",
    "on_tool_end": "tool_end",
}


@dataclass
class RunOutcome:
    status: str  # succeeded / waiting_approval / budget_exceeded / failed
    result: dict | None = None
    budget: dict | None = None
    usage: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    error: str | None = None


def _brief(value: Any, limit: int = 200) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "…"


async def stream_run(
    agent: Any,
    run_input: Any,
    config: dict,
    budget: Budget,
    emit: EmitFn | None = None,
) -> RunOutcome:
    """消费一次执行的事件流并返回结果。

    emit: 可选回调,每个公开事件(NDJSON 行 dict)同步调用一次。
    """
    events: list[dict] = []
    usage_in = usage_out = 0
    seq = 0

    def send(event: dict) -> None:
        events.append(event)
        if emit is not None:
            emit(event)

    status = "succeeded"
    error: str | None = None

    def _public(ev: dict) -> dict | None:
        etype = ev.get("event")
        mapped = _EVENT_MAP.get(etype)
        if mapped is None:
            return None
        payload: dict[str, Any] = {"name": ev.get("name")}
        if etype == "on_tool_start":
            payload["input_brief"] = _brief(ev.get("data", {}).get("input"))
        if etype == "on_tool_end":
            out = ev.get("data", {}).get("output")
            payload["output_brief"] = _brief(out if isinstance(out, str) else str(out))
        if etype == "on_chat_model_end":
            msg = ev.get("data", {}).get("output")
            meta = getattr(msg, "usage_metadata", None) or {}
            payload["usage"] = {k: meta.get(k) for k in ("input_tokens", "output_tokens")}
        return {"seq": 0, "type": mapped, **payload}

    try:
        async for ev in agent.astream_events(run_input, config, version="v2"):
            public = _public(ev)
            if public is None:
                continue
            etype = ev.get("event")

            if etype == "on_chat_model_start":
                # 先计数再检查:越界的调用既已发出,用量要如实记录(§10.4 尽力约束)
                budget.record_model()
                budget.check_model()
            elif etype == "on_tool_start":
                budget.record_tool(run_id=ev.get("run_id"))

            if public["type"] == "model_call_end":
                u = public.get("usage") or {}
                usage_in += u.get("input_tokens") or 0
                usage_out += u.get("output_tokens") or 0

            seq += 1
            public["seq"] = seq
            send(public)
    except BudgetAbort as exc:
        status = "budget_exceeded"
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — 执行失败也要返回结构化结果
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"

    snapshot = await agent.aget_state(config)
    result_obj = snapshot.values.get("structured_response")
    result = None
    if result_obj is not None:
        result = result_obj.model_dump() if hasattr(result_obj, "model_dump") else dict(result_obj)

    if status == "succeeded" and snapshot.next:  # 图被中断(等待审批),尚未到终态
        status = "waiting_approval"

    return RunOutcome(
        status=status,
        result=result,
        budget=budget.snapshot(),
        usage={"input_tokens": usage_in, "output_tokens": usage_out},
        events=events,
        error=error,
    )



