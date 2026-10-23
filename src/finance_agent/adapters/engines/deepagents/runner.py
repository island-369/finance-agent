"""Deep Agents 执行器:事件流、Skill 加载检测与执行记录(设计 §6.2、§13.3、§7.3)。

公开事件只含可观察信息:模型/工具调用、用量与简短摘要;不依赖模型内部
思维过程。Skill 加载的判定是"实际 read_file 了 /skills/<name>/ 下的文件"
(§7.3:不只记录'曾出现在提示词中');一次都没读则记录 no_skill_selected。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from finance_agent.budget import Budget, BudgetAbort

_EVENT_MAP = {
    "on_chat_model_start": "model_call_start",
    "on_chat_model_end": "model_call_end",
    "on_tool_start": "tool_start",
    "on_tool_end": "tool_end",
}


def _brief(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class RunOutcome:
    status: str  # succeeded / waiting_approval / budget_exceeded / failed
    result: dict | None = None
    budget: dict | None = None
    usage: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    error: str | None = None
    quality_flags: list[str] = field(default_factory=list)


def run_config(thread_id: str, *, recursion_limit: int = 150) -> dict:
    """统一的运行配置。

    显式 recursion_limit:引擎子 Agent 子图不继承主图 with_config 的默认值,
    实测会在 25 步(默认)触发 GraphRecursionError;预算才是本项目的
    执行边界(§10.4),图递归上限只作兜底保护。
    """
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}


def _skill_from_read(file_path: str | None) -> str | None:
    if not file_path:
        return None
    if not file_path.startswith("/skills/"):
        return None
    parts = file_path.strip("/").split("/")
    return parts[1] if len(parts) >= 2 else None


class CancelAbort(Exception):
    """外部取消请求;执行侧停止消费事件流。"""


async def stream_run(
    agent: Any,
    run_input: Any,
    config: dict,
    budget: Budget,
    *,
    max_loaded_skills: int = 3,
    emit_event: Callable[[dict], Any] | None = None,
    should_cancel: Callable[[], Any] | None = None,
) -> RunOutcome:
    """消费事件流。

    emit_event:每个公开事件的回调,可为 async(逐条写 run_events / 实时 SSE)。
    should_cancel:在模型/工具调用前检查,可为 async;真值时以 cancelled 终止
    (设计 §6.3:Worker 在模型/工具调用前后检查取消请求)。
    """
    events: list[dict] = []
    tool_calls: list[dict] = []
    loaded: list[str] = []
    usage_in = usage_out = 0
    seq = 0
    status = "succeeded"
    error: str | None = None
    quality_flags: list[str] = []

    try:
        async for ev in agent.astream_events(run_input, config, version="v2"):
            etype = ev.get("event")
            mapped = _EVENT_MAP.get(etype)
            if mapped is None:
                continue

            if etype in ("on_chat_model_start", "on_tool_start") and should_cancel is not None:
                flag = should_cancel()
                if hasattr(flag, "__await__"):
                    flag = await flag
                if flag:
                    raise CancelAbort

            if etype == "on_chat_model_start":
                budget.record_model()
                budget.check_model()
            elif etype == "on_tool_start":
                budget.record_tool(run_id=ev.get("run_id"))

            payload: dict[str, Any] = {"name": ev.get("name")}
            if etype == "on_tool_start":
                data_in = ev.get("data", {}).get("input")
                payload["input_brief"] = _brief(data_in)
                tool_calls.append({"name": ev.get("name"), "input_brief": payload["input_brief"]})
                if ev.get("name") == "read_file":
                    file_path = None
                    if isinstance(data_in, dict):
                        file_path = data_in.get("file_path")
                    elif isinstance(data_in, str):
                        try:
                            file_path = json.loads(data_in).get("file_path")
                        except (json.JSONDecodeError, AttributeError):
                            file_path = None
                    skill = _skill_from_read(file_path)
                    if skill and skill not in loaded:
                        loaded.append(skill)
                        if len(loaded) > max_loaded_skills:
                            quality_flags.append(
                                f"loaded_skills 超过 {max_loaded_skills}: {len(loaded)}"
                            )
            elif etype == "on_tool_end":
                out = ev.get("data", {}).get("output")
                payload["output_brief"] = _brief(out if isinstance(out, str) else str(out))
            elif etype == "on_chat_model_end":
                meta = getattr(ev.get("data", {}).get("output"), "usage_metadata", None) or {}
                payload["usage"] = {k: meta.get(k) for k in ("input_tokens", "output_tokens")}
                usage_in += payload["usage"].get("input_tokens") or 0
                usage_out += payload["usage"].get("output_tokens") or 0

            seq += 1
            public = {"seq": seq, "type": mapped, **payload}
            events.append(public)
            if emit_event is not None:
                res = emit_event(public)
                if hasattr(res, "__await__"):
                    await res
    except BudgetAbort as exc:
        status = "budget_exceeded"
        error = str(exc)
    except CancelAbort:
        status = "cancelled"
        error = "收到取消请求,执行已停止"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"

    snapshot = await agent.aget_state(config)
    result_obj = snapshot.values.get("structured_response")
    result = None
    if result_obj is not None:
        result = result_obj.model_dump(mode="json") if hasattr(result_obj, "model_dump") else dict(result_obj)
    if status == "succeeded" and snapshot.next:
        status = "waiting_approval"
    if status == "succeeded" and result is None:
        status = "failed"
        error = error or "执行结束但未产生结构化结果"

    return RunOutcome(
        status=status,
        result=result,
        budget=budget.snapshot(),
        usage={"input_tokens": usage_in, "output_tokens": usage_out},
        events=events,
        tool_calls=tool_calls,
        loaded_skills=loaded,
        error=error,
        quality_flags=quality_flags,
    )
