"""API 层:幂等创建、状态、取消、恢复、SSE 补读、元数据端点。"""

from __future__ import annotations


async def _create_body(objective="分析 demo-company-a 2026 年上半年净利润变化"):
    return {"objective": objective, "entity_ids": ["demo-company-a"]}


class TestCreateRun:
    async def test_create_returns_202(self, app_client):
        resp = await app_client.post("/v1/runs", json=await _create_body())
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued" and data["replayed"] is False
        assert data["run_id"].startswith("run-")
        assert "Location" in resp.headers

    async def test_idempotency_replay_and_conflict(self, app_client):
        body = await _create_body()
        headers = {"Idempotency-Key": "k-1"}
        r1 = await app_client.post("/v1/runs", json=body, headers=headers)
        r2 = await app_client.post("/v1/runs", json=body, headers=headers)
        assert r1.status_code == r2.status_code == 202
        assert r1.json()["run_id"] == r2.json()["run_id"]
        assert r2.json()["replayed"] is True

        other = await _create_body(objective="另一个目标")
        r3 = await app_client.post("/v1/runs", json=other, headers=headers)
        assert r3.status_code == 409  # 同键不同摘要

    async def test_get_run(self, app_client):
        created = (await app_client.post("/v1/runs", json=await _create_body())).json()
        resp = await app_client.get(f"/v1/runs/{created['run_id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert resp.json()["budget"]["limits"]["max_model_calls"] == 15

    async def test_missing_run_404(self, app_client):
        assert (await app_client.get("/v1/runs/nope")).status_code == 404


class TestCancelResume:
    async def test_cancel_idempotent(self, app_client):
        created = (await app_client.post("/v1/runs", json=await _create_body())).json()
        rid = created["run_id"]
        r1 = await app_client.post(f"/v1/runs/{rid}/cancel")
        r2 = await app_client.post(f"/v1/runs/{rid}/cancel")
        assert r1.status_code == r2.status_code == 202
        detail = (await app_client.get(f"/v1/runs/{rid}")).json()
        assert detail["cancel_requested"] is True

    async def test_resume_only_from_waiting_input(self, app_client):
        created = (await app_client.post("/v1/runs", json=await _create_body())).json()
        resp = await app_client.post(f"/v1/runs/{created['run_id']}/resume", json={"approve": True})
        assert resp.status_code == 409  # queued 状态不可 resume


class TestSSE:
    async def test_sse_replays_from_last_event_id(self, app_client, repo):
        created = (await app_client.post("/v1/runs", json=await _create_body())).json()
        rid = created["run_id"]
        await repo.add_event(rid, event_type="e1", payload={"n": 1}, attempt=0)
        await repo.add_event(rid, event_type="e2", payload={"n": 2}, attempt=0)
        # 推到终态,SSE 才会自然结束(活跃任务会保持连接推送——时间线语义)
        claimed = await repo.claim_next(owner="t")
        assert claimed is not None
        assert await repo.finish_run(rid, fencing_token=claimed["fencing_token"],
                                     status="succeeded", attempt=1)

        resp = await app_client.get(f"/v1/runs/{rid}/events")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "e1" in resp.text and "e2" in resp.text and "id: 1" in resp.text

        # 断开后带 Last-Event-ID 补读:只收到 seq>1 的事件
        resp2 = await app_client.get(f"/v1/runs/{rid}/events", headers={"Last-Event-ID": "1"})
        assert "e2" in resp2.text and "e1" not in resp2.text


class TestMetadata:
    async def test_skills_endpoint(self, app_client):
        data = (await app_client.get("/v1/skills")).json()
        refs = [s["ref"] for s in data["skills"]]
        assert "earnings-analysis@1.0.0" in refs
        assert all("available" in s for s in data["skills"])

    async def test_engines_endpoint(self, app_client):
        data = (await app_client.get("/v1/engines")).json()
        assert data["engines"][0]["engine_id"] == "deepagents"
        assert "checkpoint_resume" in data["engines"][0]["capabilities"]

    async def test_artifacts_empty_for_new_run(self, app_client):
        created = (await app_client.post("/v1/runs", json=await _create_body())).json()
        resp = await app_client.get(f"/v1/runs/{created['run_id']}/artifacts")
        assert resp.status_code == 200
        assert resp.json()["artifacts"] == []
