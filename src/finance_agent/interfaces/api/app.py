"""FastAPI 应用:任务接口与 SSE 事件流(设计 §13.1)。

- POST /v1/runs:202 + run_id;Idempotency-Key 同键同摘要重放,同键不同摘要 409。
- SSE 断开不终止任务(Worker 独立进程);重连后按 Last-Event-ID 从数据库补读。
- API 只返回业务状态,不序列化引擎内部对象(检查点等)。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from finance_agent.adapters.persistence.database import (
    create_engine_factory,
    dispose_engine,
    init_db,
    session_factory,
)
from finance_agent.adapters.persistence.repository import (
    TERMINAL_STATUSES,
    ConflictError,
    RunRepository,
)
from finance_agent.bootstrap import build_default_registry

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
DEFAULT_AS_OF = "2026-08-31T23:59:59+08:00"
SSE_POLL = 0.5
SSE_HEARTBEAT = 15.0

ENGINE_CAPABILITIES = [
    {
        "engine_id": "deepagents",
        "engine_version": "0.7.30",
        "adapter_version": "m2",
        "capabilities": {
            "model_tool_calling": "native(已验证)",
            "skill_progressive_loading": "native(已验证)",
            "structured_result": "native(已验证)",
            "run_events": "adapted(已验证)",
            "checkpoint_resume": "adapted(已验证;预算计数由应用任务表持久化)",
            "dynamic_tool_binding": "unsupported(首版任务启动时绑定)",
            "subagents": "native 存在,首版不依赖",
        },
    }
]


class RunCreateRequest(BaseModel):
    objective: str = Field(min_length=1)
    entity_ids: list[str] = Field(min_length=1)
    as_of: str = DEFAULT_AS_OF
    budget: dict = Field(default_factory=dict)
    interrupt_on_tool: str | None = Field(default=None, description="在指定工具前等待审批(演示用)")


class ResumeRequest(BaseModel):
    approve: bool = True


def create_app(*, repo: RunRepository | None = None, runtime_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine_factory()
        await init_db(engine)
        app.state.repo = repo or RunRepository(session_factory(engine), engine)
        app.state.engine = engine
        app.state.runtime_dir = runtime_dir or RUNTIME_DIR
        yield
        await dispose_engine(engine)

    app = FastAPI(title="金融研究 Agent", version="0.1.0", lifespan=lifespan)

    from fastapi.middleware.cors import CORSMiddleware

    # 本机/受控个人环境(设计 §13.1);开放多用户前收紧来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5180", "http://127.0.0.1:5173", "http://127.0.0.1:5180"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from finance_agent.interfaces.api.admin import router as admin_router

    app.include_router(admin_router)

    def get_repo() -> RunRepository:
        return app.state.repo  # type: ignore[no-any-return]

    # ------------------------------------------------------------ 创建 ----

    @app.post("/v1/runs", status_code=202)
    async def create_run(
        req: RunCreateRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        from finance_agent.application.run_service import prepare_run

        digest = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
        try:
            # 任务快照(§7.3):Skill 解析与只读视图在创建时物化,执行中不再变化
            plan = prepare_run(
                objective=req.objective,
                entity_ids=req.entity_ids,
                as_of=req.as_of,
                tool_registry=build_default_registry(),
                runtime_dir=app.state.runtime_dir,
            )
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"任务创建失败: {e}") from e

        budget_limits = {
            "max_model_calls": req.budget.get("max_model_calls", 15),
            "max_tool_calls": req.budget.get("max_tool_calls", 30),
        }
        config = {
            "view_root": str(plan.view_root),
            "bound_tools": [f"{n}@{m}" for n, m in plan.bound_tool_refs],
            "skill_candidates": [r.ref for r in plan.candidates],
            "interrupt_on": {req.interrupt_on_tool.replace(".", "_"): True} if req.interrupt_on_tool else None,
            "created_by": "api",
        }
        try:
            run, replayed = await get_repo().create_run(
                objective=req.objective,
                entity_ids=req.entity_ids,
                as_of=req.as_of,
                config=config,
                budget_limits=budget_limits,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        response.headers["Location"] = f"/v1/runs/{run['id']}"
        return {
            "run_id": run["id"],
            "status": run["status"],
            "replayed": replayed,
            "skill_candidates": config["skill_candidates"],
        }

    # ------------------------------------------------------------ 查询 ----

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        run = await get_repo().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        result = run.get("result") or {}
        return {
            "run_id": run["id"],
            "status": run["status"],
            "objective": run["objective"],
            "entity_ids": run["entity_ids"],
            "as_of": run["as_of"],
            "attempt": run["attempt"],
            "max_attempts": run["max_attempts"],
            "error": run["error"],
            "cancel_requested": run["cancel_requested_at"] is not None,
            "budget": {"limits": run["budget_limits"], "used": run["budget_used"]},
            "summary": result.get("summary"),
            "artifact_kinds": [a["kind"] for a in await get_repo().artifacts_of(run["id"])],
            "created_at": run["created_at"].isoformat() if run["created_at"] else None,
        }

    @app.get("/v1/runs/{run_id}/artifacts")
    async def get_artifacts(run_id: str) -> dict:
        if await get_repo().get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        items = await get_repo().artifacts_of(run_id)
        return {"run_id": run_id, "artifacts": [{**a, "created_at": a["created_at"].isoformat()} for a in items]}

    # ------------------------------------------------------------ 动作 ----

    @app.post("/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str) -> dict:
        repo = get_repo()
        if await repo.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        ok = await repo.request_cancel(run_id)
        return {"run_id": run_id, "cancel_requested": ok,
                "note": "取消请求已记录;Worker 在下次模型/工具调用前生效,已完成的外部调用不可撤回"}

    @app.post("/v1/runs/{run_id}/resume", status_code=202)
    async def resume_run(run_id: str, req: ResumeRequest) -> dict:
        repo = get_repo()
        if await repo.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        updated = await repo.set_resume_action(run_id, "approve" if req.approve else "reject")
        if updated is None:
            raise HTTPException(status_code=409, detail="当前状态不可恢复(仅 waiting_input)")
        return {"run_id": run_id, "status": updated["status"], "resume_action": updated["resume_action"]}

    # ------------------------------------------------------------ SSE ----

    @app.get("/v1/runs/{run_id}/events")
    async def stream_events(run_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        repo = get_repo()
        if await repo.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        after = int(last_event_id) if last_event_id else 0

        async def gen() -> AsyncIterator[bytes]:
            nonlocal after
            heartbeat_at = asyncio.get_event_loop().time()
            while True:
                events = await repo.events_since(run_id, after_seq=after)
                for e in events:
                    after = e["seq"]
                    data = {
                        "event_id": e["event_id"],
                        "run_id": run_id,
                        "seq": e["seq"],
                        "type": e["type"],
                        "attempt": e["attempt"],
                        "payload": e["payload"],
                        "occurred_at": e["occurred_at"].isoformat() if e["occurred_at"] else None,
                    }
                    yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()
                run = await repo.get_run(run_id)
                if run is None:
                    return
                if run["status"] in TERMINAL_STATUSES and not events:
                    yield b"event: stream.end\ndata: {}\n\n"
                    return
                now = asyncio.get_event_loop().time()
                if now - heartbeat_at >= SSE_HEARTBEAT:
                    heartbeat_at = now
                    yield b": ping\n\n"
                await asyncio.sleep(SSE_POLL)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ 元数据 ----

    @app.get("/v1/skills")
    async def list_skills() -> dict:
        from finance_agent.skills.registry import scan_skill_dir
        from finance_agent.skills.resolver import resolve_skills

        records = scan_skill_dir(PROJECT_ROOT / "skills")
        resolved = resolve_skills(records, build_default_registry())
        return {
            "skills": [
                {"ref": r.ref, "available": r.available, "reason": r.reason,
                 "degraded_tools": list(r.degraded_tools), "description": r.record.description}
                for r in resolved
            ]
        }

    @app.get("/v1/engines")
    async def list_engines() -> dict:
        return {"engines": ENGINE_CAPABILITIES}

    return app


app = create_app()
