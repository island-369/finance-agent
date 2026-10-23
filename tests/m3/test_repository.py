"""仓储核心行为:领取/租约/fencing/幂等(退出条件 3、4 的基础)。"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from finance_agent.adapters.persistence.database import (
    create_engine_factory,
    dispose_engine,
    session_factory,
)
from finance_agent.adapters.persistence.repository import ConflictError, RunRepository

FMT = "%Y-%m-%d %H:%M:%S.%f"


async def _create(repo: RunRepository, rid="run-t1", **kw) -> dict:
    run, _ = await repo.create_run(
        objective="测试任务", entity_ids=["demo-company-a"], as_of="2026-08-31T23:59:59+08:00",
        config={"view_root": "/tmp/x", "bound_tools": ["documents.search@1"]},
        budget_limits={"max_model_calls": 5, "max_tool_calls": 5}, run_id=rid, **kw,
    )
    return run


async def _expire_all_leases() -> None:
    engine = create_engine_factory(os.environ["FINANCE_AGENT_DB_URL"])
    async with session_factory(engine)() as s, s.begin():
        from sqlalchemy import text

        past = (datetime.now(UTC) - timedelta(seconds=1)).strftime(FMT)
        await s.execute(text("UPDATE runs SET lease_expires_at = :t"), {"t": past})
    await dispose_engine(engine)


class TestClaimLease:
    async def test_claim_increments_attempt_and_fencing(self, repo):
        await _create(repo)
        run = await repo.claim_next(owner="w1")
        assert run is not None and run["attempt"] == 1 and run["fencing_token"] == 1
        assert run["status"] == "running" and run["lease_owner"] == "w1"
        assert await repo.claim_next(owner="w2") is None  # 租约有效期内不可重复领取

    async def test_expired_lease_reclaimable(self, repo):
        await _create(repo)
        first = await repo.claim_next(owner="w1")
        assert first is not None
        await _expire_all_leases()  # 模拟 Worker 死亡后租约过期
        second = await repo.claim_next(owner="w2")
        assert second is not None
        assert second["attempt"] == 2 and second["fencing_token"] == 2

    async def test_renew_lease_requires_owner_and_token(self, repo):
        await _create(repo)
        run = await repo.claim_next(owner="w1")
        assert run is not None
        assert await repo.renew_lease(run["id"], owner="w1", fencing_token=run["fencing_token"])
        assert not await repo.renew_lease(run["id"], owner="w1", fencing_token=run["fencing_token"] + 5)
        assert not await repo.renew_lease(run["id"], owner="other", fencing_token=run["fencing_token"])


class TestFencing:
    async def test_stale_token_cannot_finish(self, repo):
        await _create(repo)
        a = await repo.claim_next(owner="w1")
        await _expire_all_leases()  # 旧 Worker 失去租约,新 Worker 领取
        b = await repo.claim_next(owner="w2")
        assert a is not None and b is not None
        assert b["fencing_token"] > a["fencing_token"]

        # 旧 Worker(旧 token)提交:被拒绝
        assert not await repo.finish_run(a["id"], fencing_token=a["fencing_token"],
                                         status="succeeded", attempt=a["attempt"],
                                         result={"objective": "旧"}, artifact_kind="research-result.v1",
                                         artifact_content={"objective": "旧"})
        # 新 Worker 提交:成功
        assert await repo.finish_run(b["id"], fencing_token=b["fencing_token"],
                                     status="succeeded", attempt=b["attempt"],
                                     result={"objective": "新"}, artifact_kind="research-result.v1",
                                     artifact_content={"objective": "新"})
        final = await repo.get_run(a["id"])
        assert final is not None
        assert final["status"] == "succeeded"
        assert final["result"]["objective"] == "新"  # 旧 Worker 没有覆盖结果

    async def test_finish_twice_no_duplicate_artifact(self, repo):
        run = await _create(repo)
        claimed = await repo.claim_next(owner="w1")
        assert claimed is not None
        assert await repo.finish_run(run["id"], fencing_token=claimed["fencing_token"],
                                     status="succeeded", attempt=1, result={"a": 1},
                                     artifact_kind="research-result.v1", artifact_content={"a": 1})
        # 终态后再提交(同 token):状态已非 running/validating,拒绝
        assert not await repo.finish_run(run["id"], fencing_token=claimed["fencing_token"],
                                         status="succeeded", attempt=1, result={"a": 2},
                                         artifact_kind="research-result.v1", artifact_content={"a": 2})
        assert len(await repo.artifacts_of(run["id"])) == 1


class TestIdempotency:
    async def test_same_key_same_digest_replays(self, repo):
        r1, replayed1 = await repo.create_run(
            objective="o", entity_ids=["demo-company-a"], as_of="2026-08-31T23:59:59+08:00",
            config={}, budget_limits={}, run_id="run-i1",
            idempotency_key="key-1", request_digest="d1",
        )
        r2, replayed2 = await repo.create_run(
            objective="o", entity_ids=["demo-company-a"], as_of="2026-08-31T23:59:59+08:00",
            config={}, budget_limits={}, run_id="run-i2",
            idempotency_key="key-1", request_digest="d1",
        )
        assert not replayed1 and replayed2
        assert r1["id"] == r2["id"]

    async def test_same_key_different_digest_conflicts(self, repo):
        await _create(repo, "run-i3", idempotency_key="key-2", request_digest="d1")
        with pytest.raises(ConflictError):
            await _create(repo, "run-i4", idempotency_key="key-2", request_digest="d2")


class TestEvents:
    async def test_events_seq_monotonic_and_since(self, repo):
        run = await _create(repo)
        s1 = await repo.add_event(run["id"], event_type="t1", payload={}, attempt=1)
        s2 = await repo.add_event(run["id"], event_type="t2", payload={}, attempt=1)
        assert s2 == s1 + 1
        events = await repo.events_since(run["id"], after_seq=0)
        assert [e["seq"] for e in events] == [1, 2]
        tail = await repo.events_since(run["id"], after_seq=1)
        assert [e["seq"] for e in tail] == [2]
