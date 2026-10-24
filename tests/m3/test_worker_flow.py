"""Worker/执行器集成:五条 M3 退出条件的端到端验证(脚本模型,无外部依赖)。

1. 断开前端不会丢任务 —— 任务落库后由 Worker 独立执行,与客户端无关。
2. 中断 Worker 后可按声明恢复 —— 崩溃(requeue)后第二次领取从引擎检查点
   invoke(None) 续跑,预算沿用已消耗计数。
3. 旧 Worker 不能覆盖结果 —— fencing token 拒绝失租者(另见 test_repository)。
4. 重复请求不会产生重复产物 —— Idempotency-Key + (run_id, kind) 唯一。
5. 不可恢复场景有真实错误说明 —— 尝试耗尽后 failed 且保留错误文本。
"""

from __future__ import annotations

from pathlib import Path

from finance_agent.adapters.engines.deepagents.executor import execute_run
from finance_agent.adapters.persistence.repository import RunRepository
from finance_agent.application.run_service import prepare_run
from finance_agent.bootstrap import build_default_registry
from tests.m2.helpers import (
    ReactiveScriptedModel,
    read_skill_msg,
    research_result_msg,
    tool_call_msg,
)

AS_OF = "2026-08-31T23:59:59+08:00"
OBJECTIVE = "分析 demo-company-a 2026 年上半年净利润变化"


async def _make_run(repo: RunRepository, tmp_path: Path, rid: str, *, max_attempts: int = 3, **config_extra) -> dict:
    plan = prepare_run(
        objective=OBJECTIVE, entity_ids=["demo-company-a"], as_of=AS_OF,
        tool_registry=build_default_registry(), runtime_dir=tmp_path / "runtime",
    )
    config = {
        "view_root": str(plan.view_root),
        "bound_tools": [f"{n}@{m}" for n, m in plan.bound_tool_refs],
        "interrupt_on": None,
        **config_extra,
    }
    run, _ = await repo.create_run(
        objective=OBJECTIVE, entity_ids=["demo-company-a"], as_of=AS_OF,
        config=config, budget_limits={"max_model_calls": 15, "max_tool_calls": 30},
        run_id=rid, max_attempts=max_attempts,
    )
    return run


def _full_script() -> list:
    return [
        read_skill_msg("earnings-analysis", "c1"),
        tool_call_msg("finance_get_metrics", {
            "entity_id": "demo-company-a", "metric": "net_profit", "basis": "cumulative",
            "period_start": "2025-01-01", "period_end": "2026-06-30",
        }, "c2"),
        tool_call_msg("finance_get_metrics", {
            "entity_id": "demo-company-a", "metric": "revenue", "basis": "cumulative",
            "period_start": "2025-01-01", "period_end": "2026-06-30",
        }, "c2b"),
        tool_call_msg("finance_calculate_growth", {
            "current_observation_id": "obs-a-np-cum-2026h1-v2",
            "base_observation_id": "obs-a-np-cum-2025h1",
        }, "c3"),
        research_result_msg(OBJECTIVE, "demo-company-a"),
    ]


def _submit(result_args: dict, call_id: str = "c9"):
    return tool_call_msg("ResearchResult", result_args, call_id)


def _poison(messages):
    raise RuntimeError("模拟模型服务中断")


class TestHappyPath:
    async def test_worker_completes_without_client(self, repo, tmp_path: Path):
        """退出条件 1:任务在库中由 Worker 独立完成;产物/事件/预算齐全。"""
        await _make_run(repo, tmp_path, "run-w1")
        claimed = await repo.claim_next(owner="w1")
        assert claimed is not None

        final = await execute_run(
            claimed, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=_full_script()),
        )
        assert final == "succeeded"
        run = await repo.get_run("run-w1")
        assert run["status"] == "succeeded"
        assert run["result"]["summary"]

        artifacts = await repo.artifacts_of("run-w1")
        assert [a["kind"] for a in artifacts] == ["research-result.v1"]

        events = await repo.events_since("run-w1", after_seq=0)
        types = [e["type"] for e in events]
        assert "run.attempt_started" in types
        assert "engine.tool_start" in types
        assert "run.skills_loaded" in types
        assert "run.status_changed" in types
        assert types[-1] == "run.skills_loaded"  # finish 之后追加
        assert run["budget_used"]["model_calls"] == 5
        assert run["budget_used"]["tool_calls"] == 4

    async def test_skill_loaded_event(self, repo, tmp_path: Path):
        await _make_run(repo, tmp_path, "run-w1b")
        claimed = await repo.claim_next(owner="w1")
        assert claimed is not None
        await execute_run(claimed, repo, runtime_dir=tmp_path / "runtime",
                          model_factory=lambda run: ReactiveScriptedModel(responses=_full_script()))
        events = await repo.events_since("run-w1b", after_seq=0)
        loaded = next(e for e in events if e["type"] == "run.skills_loaded")
        assert loaded["payload"]["loaded"] == ["earnings-analysis"]
        assert loaded["payload"]["no_skill_selected"] is False


class TestCrashRecovery:
    async def test_crash_then_resume_from_checkpoint_with_budget(self, repo, tmp_path: Path):
        """退出条件 2:第 1 次尝试在模型第 2 次调用处崩溃;第 2 次领取从
        检查点续跑(invoke None),预算沿用已消耗计数(§10.4)。"""
        await _make_run(repo, tmp_path, "run-c1")

        a1 = await repo.claim_next(owner="w1")
        assert a1 is not None
        script1 = [_full_script()[0], _poison]  # read_file 成功后模型崩溃
        final1 = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=script1),
        )
        assert final1 == "requeued"
        mid = await repo.get_run("run-c1")
        assert mid["status"] == "queued" and mid["attempt"] == 1
        assert mid["error"] and "模拟" in mid["error"]  # 真实错误说明
        # 第 2 次模型调用已 START(如实计数)后才崩溃 → model_calls=2
        assert mid["budget_used"] == {"max_model_calls": 15, "max_tool_calls": 30,
                                      "model_calls": 2, "tool_calls": 1}

        a2 = await repo.claim_next(owner="w2")  # 租约内重新领取(模拟恢复程序)
        assert a2 is not None and a2["attempt"] == 2
        final2 = await execute_run(
            a2, repo, runtime_dir=tmp_path / "runtime",
            # 崩溃恢复以 None 续跑:模型从检查点之后的调用继续
            model_factory=lambda run: ReactiveScriptedModel(responses=_full_script()[1:]),
        )
        assert final2 == "succeeded"
        done = await repo.get_run("run-c1")
        assert done["status"] == "succeeded"
        # 预算沿第一次尝试的计数累计:2+4 模型调用 / 1+3 工具调用(§10.4)
        assert done["budget_used"]["model_calls"] == 6
        assert done["budget_used"]["tool_calls"] == 4

    async def test_attempts_exhausted_fails_with_real_error(self, repo, tmp_path: Path):
        """退出条件 5:尝试耗尽后 failed,错误文本保留。"""
        await _make_run(repo, tmp_path, "run-c2", max_attempts=1)
        a1 = await repo.claim_next(owner="w1")
        assert a1 is not None and a1["max_attempts"] == 1
        final = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda r: ReactiveScriptedModel(responses=[_poison]),
        )
        assert final == "failed"
        failed = await repo.get_run("run-c2")
        assert failed["status"] == "failed"
        assert failed["error"] and "已达最大尝试次数" in failed["error"]


class TestApprovalFlow:
    async def test_interrupt_wait_resume_approve(self, repo, tmp_path: Path):
        """工具审批中断 → waiting_input → resume(approve) → 每个门控调用逐一批准
        → 从检查点继续完成。"""
        await _make_run(repo, tmp_path, "run-h1",
                        interrupt_on={"finance_get_metrics": True})
        a1 = await repo.claim_next(owner="w1")
        assert a1 is not None
        final1 = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=[_full_script()[1]]),
        )
        assert final1 == "waiting_input"
        assert (await repo.get_run("run-h1"))["status"] == "waiting_input"

        # 第一次批准 → 第二个门控调用(收入查询)再次等待审批
        updated = await repo.set_resume_action("run-h1", "approve")
        assert updated is not None and updated["status"] == "queued"
        a2 = await repo.claim_next(owner="w1")
        assert a2 is not None and a2["resume_action"] == "approve"
        final2 = await execute_run(
            a2, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=[_full_script()[2]]),
        )
        assert final2 == "waiting_input"
        assert (await repo.get_run("run-h1"))["status"] == "waiting_input"

        # 第二次批准 → 计算并提交结果 → 校验通过 → succeeded
        updated = await repo.set_resume_action("run-h1", "approve")
        assert updated is not None and updated["status"] == "queued"
        a3 = await repo.claim_next(owner="w1")
        assert a3 is not None and a3["resume_action"] == "approve"
        final3 = await execute_run(
            a3, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=_full_script()[3:]),
        )
        assert final3 == "succeeded"
        assert (await repo.get_run("run-h1"))["status"] == "succeeded"


class TestCancel:
    async def test_cancel_before_model_call(self, repo, tmp_path: Path):
        await _make_run(repo, tmp_path, "run-x1")
        a1 = await repo.claim_next(owner="w1")
        assert a1 is not None
        await repo.request_cancel("run-x1")
        final = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda run: ReactiveScriptedModel(responses=_full_script()),
        )
        assert final == "cancelled"
        run = await repo.get_run("run-x1")
        assert run["status"] == "cancelled"
        assert run["cancel_requested_at"] is not None


def _bad_submit():
    """引用了不存在的观测(硬错误)的结果提交。"""
    return _submit({
        "objective": OBJECTIVE,
        "researched_at": "2026-10-24T00:00:00+00:00",
        "entity_ids": ["demo-company-a"],
        "summary": "净利润 2.72 亿元。",
        "key_findings": [{"statement": "净利润 2.72 亿元", "kind": "fact", "refs": ["obs-ghost"]}],
        "metric_refs": ["obs-ghost"],
    })


def _pending_submit():
    """引用有效但含无法映射的派生数字(可修复问题)。"""
    return _submit({
        "objective": OBJECTIVE,
        "researched_at": "2026-10-24T00:00:00+00:00",
        "entity_ids": ["demo-company-a"],
        "summary": "2026H1 净利润 2.72 亿元(obs-a-np-cum-2026h1-v2),利润率约 5.55%。",
        "key_findings": [{"statement": "净利润 2.72 亿元(obs-a-np-cum-2026h1-v2)", "kind": "fact",
                          "refs": ["obs-a-np-cum-2026h1-v2"]}],
        "metric_refs": ["obs-a-np-cum-2026h1-v2"],
    })


class TestRepairLoop:
    async def _script_prefix(self):
        return _full_script()[:4]  # read_skill + 两个 metrics + growth

    async def test_repair_then_succeed(self, repo, tmp_path: Path):
        """硬错误 → 修复反馈 → 模型重新提交正确结果 → succeeded。"""
        await _make_run(repo, tmp_path, "run-r1")
        a1 = await repo.claim_next(owner="w1")
        script = [*await self._script_prefix(), _bad_submit(),
                  research_result_msg(OBJECTIVE, "demo-company-a")]
        final = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda r: ReactiveScriptedModel(responses=script),
        )
        assert final == "succeeded"
        run = await repo.get_run("run-r1")
        assert run["status"] == "succeeded"
        events = await repo.events_since("run-r1", 0)
        kinds = [e["type"] for e in events]
        assert "run.validating" in kinds and "run.repair_feedback" in kinds
        validating = [e for e in events if e["type"] == "run.validating"]
        assert validating[0]["payload"]["hard"]  # 第一轮确有硬错误
        assert not validating[-1]["payload"]["hard"] and not validating[-1]["payload"]["repairable"]
        # 修复计入预算:6 次模型调用(5 正常 + 1 修复轮)
        assert run["budget_used"]["model_calls"] == 6

    async def test_hard_error_exhausted_fails_definitively(self, repo, tmp_path: Path):
        """两轮修复后引用错误仍在 → failed(确定性失败,不 requeue)。"""
        await _make_run(repo, tmp_path, "run-r2")
        a1 = await repo.claim_next(owner="w1")
        script = [*await self._script_prefix(), _bad_submit()]
        final = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda r: ReactiveScriptedModel(responses=script, hold_last=True),
        )
        assert final == "failed"
        run = await repo.get_run("run-r2")
        assert run["status"] == "failed"
        assert "结果校验未通过" in run["error"]
        # 确定性失败:没有任何 requeued 事件
        kinds = [e["type"] for e in await repo.events_since("run-r2", 0)]
        assert "run.requeued" not in kinds

    async def test_repairable_exhausted_yields_completed_partial(self, repo, tmp_path: Path):
        """仅剩数字映射问题 → completed_partial + pending_review 标记 + 产物。"""
        await _make_run(repo, tmp_path, "run-r3")
        a1 = await repo.claim_next(owner="w1")
        script = [*await self._script_prefix(), _pending_submit()]
        final = await execute_run(
            a1, repo, runtime_dir=tmp_path / "runtime",
            model_factory=lambda r: ReactiveScriptedModel(responses=script, hold_last=True),
        )
        assert final == "completed_partial"
        run = await repo.get_run("run-r3")
        assert run["status"] == "completed_partial"
        assert "pending_review" in run["result"]["quality_flags"]
        assert [a["kind"] for a in await repo.artifacts_of("run-r3")] == ["research-result.v1"]
        # 无硬错误:引用全部有效
        validating = [e for e in await repo.events_since("run-r3", 0) if e["type"] == "run.validating"]
        assert validating[-1]["payload"]["hard"] == []
