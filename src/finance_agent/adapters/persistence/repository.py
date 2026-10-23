"""任务仓储:领取、租约、fencing token、幂等创建与结果提交(设计 §10)。

约定:
- 领取是短事务:SQLite 用 UPDATE..RETURNING 一次完成选择+领取;
  PostgreSQL 用 SELECT..FOR UPDATE SKIP LOCKED + UPDATE,不跨模型调用
  持有数据库锁(§4.3)。
- 终态写入(状态+产物+最终事件,同一事务)必须携带当前 fencing token;
  token 不匹配(旧 Worker)时更新 0 行,返回 False,调用方放弃(§10.1)。
- 幂等创建:Idempotency-Key + 请求摘要;同键同摘要返回原任务,同键不同
  摘要抛 ConflictError(§10.3)。

常规读写走 ORM(JSON 列类型自动转换);领取语句为纯标量更新,用原生 SQL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finance_agent.adapters.persistence.models import Artifact, IdempotencyKey, Run, RunEvent

TERMINAL_STATUSES = {"succeeded", "completed_partial", "failed", "cancelled"}


class ConflictError(Exception):
    """同 Idempotency-Key 不同请求摘要。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _run_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "objective": run.objective,
        "entity_ids": run.entity_ids,
        "as_of": run.as_of,
        "engine": run.engine,
        "config": run.config,
        "budget_limits": run.budget_limits,
        "budget_used": run.budget_used,
        "attempt": run.attempt,
        "max_attempts": run.max_attempts,
        "lease_owner": run.lease_owner,
        "lease_expires_at": run.lease_expires_at,
        "fencing_token": run.fencing_token,
        "cancel_requested_at": run.cancel_requested_at,
        "resume_action": run.resume_action,
        "error": run.error,
        "result": run.result,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


class RunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine) -> None:
        self._sessions = sessions
        self._dialect = engine.dialect.name

    # ------------------------------------------------------------ 创建 ----

    async def create_run(
        self,
        *,
        objective: str,
        entity_ids: list[str],
        as_of: str,
        config: dict,
        budget_limits: dict,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        request_digest: str | None = None,
        run_id: str | None = None,
    ) -> tuple[dict, bool]:
        """创建 queued 任务;返回 (run, replayed)。同键不同摘要抛 ConflictError。"""
        rid = run_id or f"run-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        now = _now()
        async with self._sessions() as session, session.begin():
            if idempotency_key is not None:
                existing = (
                    await session.execute(
                        select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if request_digest is not None and existing.request_digest != request_digest:
                        msg = f"Idempotency-Key 已用于不同的请求内容(key={idempotency_key})"
                        raise ConflictError(msg)
                    run = await session.get(Run, existing.run_id)
                    assert run is not None
                    return (_run_dict(run), True)
                session.add(
                    IdempotencyKey(
                        key=idempotency_key, request_digest=request_digest or "", run_id=rid, created_at=now
                    )
                )
            session.add(
                Run(
                    id=rid,
                    status="queued",
                    objective=objective,
                    entity_ids=entity_ids,
                    as_of=as_of,
                    engine="deepagents",
                    config=config,
                    budget_limits=budget_limits,
                    budget_used={},
                    attempt=0,
                    max_attempts=max_attempts,
                    fencing_token=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        run = await self.get_run(rid)
        assert run is not None
        return (run, False)

    # ------------------------------------------------------------ 查询 ----

    async def get_run(self, run_id: str) -> dict | None:
        async with self._sessions() as session:
            run = await session.get(Run, run_id)
            return _run_dict(run) if run else None

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with self._sessions() as session:
            run = await session.get(Run, run_id)
            return bool(run and run.cancel_requested_at is not None)

    async def events_since(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                    .order_by(RunEvent.seq)
                    .limit(limit)
                )
            ).scalars()
            return [
                {
                    "seq": e.seq,
                    "event_id": e.event_id,
                    "type": e.type,
                    "attempt": e.attempt,
                    "payload": e.payload,
                    "occurred_at": e.occurred_at,
                }
                for e in rows
            ]

    async def artifacts_of(self, run_id: str) -> list[dict]:
        async with self._sessions() as session:
            rows = (
                await session.execute(select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.kind))
            ).scalars()
            return [{"kind": a.kind, "content": a.content, "created_at": a.created_at} for a in rows]

    # ------------------------------------------------------------ 领取 ----

    async def claim_next(self, *, owner: str, lease_seconds: int = 120) -> dict | None:
        now = _now()
        expires = now + timedelta(seconds=lease_seconds)
        # 原生 SQL 的时间参数用字符串绑定,格式与 SQLAlchemy 的 DATETIME
        # 存储一致(无时区后缀;内部统一 UTC)。避免驱动对 datetime 绑定的
        # 方言差异;字典序比较与时间序等价。
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        now_s, expires_s = now.strftime(fmt), expires.strftime(fmt)
        claimable = (
            "(status = 'queued') OR (status = 'running' AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at < :now)"
        )
        async with self._sessions() as session, session.begin():
            if self._dialect == "postgresql":
                row = (
                    await session.execute(
                        text(
                            f"SELECT id FROM runs WHERE {claimable} "
                            "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
                        ),
                        {"now": now_s},
                    )
                ).first()
                if row is None:
                    return None
                claim_sql = (
                    "UPDATE runs SET status='running', lease_owner=:owner, lease_expires_at=:exp, "
                    "attempt=attempt+1, fencing_token=fencing_token+1, updated_at=:now "
                    "WHERE id = :id AND status IN ('queued','running') RETURNING id"
                )
                params: dict = {"owner": owner, "exp": expires_s, "now": now_s, "id": row.id}
            else:
                claim_sql = (
                    "UPDATE runs SET status='running', lease_owner=:owner, lease_expires_at=:exp, "
                    "attempt=attempt+1, fencing_token=fencing_token+1, updated_at=:now "
                    f"WHERE id = (SELECT id FROM runs WHERE {claimable} "
                    "ORDER BY created_at, id LIMIT 1) RETURNING id"
                )
                params = {"owner": owner, "exp": expires_s, "now": now_s}
            got = (await session.execute(text(claim_sql), params)).first()
            if got is None:
                return None
            rid = got[0]
        run = await self.get_run(rid)
        assert run is not None
        return run

    async def renew_lease(self, run_id: str, *, owner: str, fencing_token: int, lease_seconds: int = 120) -> bool:
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id,
                        Run.lease_owner == owner,
                        Run.fencing_token == fencing_token,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
            run.updated_at = _now()
            return True

    # ------------------------------------------------------------ 写入 ----

    async def _add_event_tx(
        self, session: AsyncSession, run_id: str, event_type: str, payload: dict, attempt: int
    ) -> int:
        max_seq = (
            await session.execute(
                text("SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id = :id"),
                {"id": run_id},
            )
        ).scalar_one()
        seq = int(max_seq) + 1
        session.add(
            RunEvent(
                run_id=run_id,
                seq=seq,
                event_id=f"evt-{uuid.uuid4().hex[:12]}",
                type=event_type,
                attempt=attempt,
                payload=payload,
                occurred_at=_now(),
            )
        )
        return seq

    async def add_event(self, run_id: str, *, event_type: str, payload: dict, attempt: int) -> int:
        async with self._sessions() as session, session.begin():
            return await self._add_event_tx(session, run_id, event_type, payload, attempt)

    async def update_budget(self, run_id: str, *, fencing_token: int, budget_used: dict) -> bool:
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id, Run.fencing_token == fencing_token, Run.status == "running"
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.budget_used = budget_used
            run.updated_at = _now()
            return True

    async def requeue(self, run_id: str, *, fencing_token: int, error: str | None) -> bool:
        """可恢复失败:回到 queued(检查点仍在,下次领取从检查点续跑)。"""
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id, Run.fencing_token == fencing_token, Run.status == "running"
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.status = "queued"
            run.lease_owner = None
            run.lease_expires_at = None
            run.error = error
            run.updated_at = _now()
            await self._add_event_tx(session, run_id, "run.requeued", {"error": error}, attempt=run.attempt)
            return True

    async def finish_run(
        self,
        run_id: str,
        *,
        fencing_token: int,
        status: str,
        attempt: int,
        result: dict | None = None,
        artifact_kind: str | None = None,
        artifact_content: dict | None = None,
        error: str | None = None,
    ) -> bool:
        """终态提交:状态+产物+最终事件同事务;fencing 不匹配返回 False。"""
        if status not in TERMINAL_STATUSES:
            msg = f"非法终态: {status}"
            raise ValueError(msg)
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id,
                        Run.fencing_token == fencing_token,
                        Run.status.in_(["running", "validating"]),
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.status = status
            run.result = result
            run.error = error
            run.lease_owner = None
            run.lease_expires_at = None
            run.resume_action = None
            run.updated_at = _now()
            if artifact_kind is not None and artifact_content is not None:
                exists = (
                    await session.execute(
                        select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == artifact_kind)
                    )
                ).scalar_one_or_none()
                if exists is None:  # 唯一约束兜底;已存在时保留首份
                    session.add(
                        Artifact(run_id=run_id, kind=artifact_kind, content=artifact_content, created_at=_now())
                    )
            await self._add_event_tx(
                session, run_id, "run.status_changed", {"status": status, "error": error}, attempt=attempt
            )
            return True

    async def mark_validating(self, run_id: str, *, fencing_token: int) -> None:
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(Run.id == run_id, Run.fencing_token == fencing_token)
                )
            ).scalar_one_or_none()
            if run is not None:
                run.status = "validating"
                run.updated_at = _now()

    async def mark_waiting_input(self, run_id: str, *, fencing_token: int, attempt: int, note: str | None = None) -> bool:
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id, Run.fencing_token == fencing_token, Run.status == "running"
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.status = "waiting_input"
            run.lease_owner = None
            run.lease_expires_at = None
            run.updated_at = _now()
            await self._add_event_tx(session, run_id, "run.waiting_input", {"note": note}, attempt=attempt)
            return True

    # ------------------------------------------------------------ 请求 ----

    async def request_cancel(self, run_id: str) -> bool:
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(
                        Run.id == run_id,
                        Run.status.in_(["queued", "running", "validating", "waiting_input"]),
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            if run.cancel_requested_at is None:  # 幂等:重复取消不覆盖首次时间
                run.cancel_requested_at = _now()
                run.updated_at = _now()
            return True

    async def set_resume_action(self, run_id: str, action: str) -> dict | None:
        """审批/恢复:waiting_input → queued,携带 resume_action。"""
        if action not in ("approve", "reject"):
            msg = f"非法 resume 动作: {action}"
            raise ValueError(msg)
        async with self._sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run).where(Run.id == run_id, Run.status == "waiting_input")
                )
            ).scalar_one_or_none()
            if run is None:
                return None
            run.status = "queued"
            run.resume_action = action
            run.updated_at = _now()
            await self._add_event_tx(session, run_id, "run.resume_requested", {"action": action}, attempt=run.attempt)
        return await self.get_run(run_id)
