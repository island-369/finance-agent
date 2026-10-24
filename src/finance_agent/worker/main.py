"""Worker 主循环。

- 短事务领取 queued(或租约过期的 running)任务;执行期间周期性续租。
- 数据库锁不跨模型调用持有:领取提交后才进入引擎执行。
- 优雅退出:SIGINT/SIGTERM 后不再领取新任务,当前任务执行完退出。
- 单机单 Worker 为 M3 默认形态;多 Worker 依赖 PG 的 FOR UPDATE SKIP LOCKED。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

from finance_agent.adapters.engines.deepagents.executor import default_model_factory, execute_run
from finance_agent.adapters.persistence.database import (
    create_engine_factory,
    init_db,
    session_factory,
)
from finance_agent.adapters.persistence.repository import RunRepository

POLL_INTERVAL = 1.0
LEASE_SECONDS = 120
RENEW_INTERVAL = LEASE_SECONDS / 3


def _owner_id() -> str:
    return os.environ.get("FINANCE_AGENT_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"


async def run_worker(*, once: bool = False, model_factory=None) -> int:
    engine = create_engine_factory()
    await init_db(engine)
    repo = RunRepository(session_factory(engine), engine)
    owner = _owner_id()
    runtime_dir = Path(os.environ.get("FINANCE_AGENT_RUNTIME_DIR", "data/runtime"))
    (runtime_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    model_factory = model_factory or default_model_factory
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    print(f"[worker:{owner}] started, poll={POLL_INTERVAL}s lease={LEASE_SECONDS}s", flush=True)
    executed = 0
    while not stop.is_set():
        run = await repo.claim_next(owner=owner, lease_seconds=LEASE_SECONDS)
        if run is None:
            if once:
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
            except TimeoutError:
                pass
            continue

        print(f"[worker:{owner}] claim {run['id']} attempt={run['attempt']} "
              f"fencing={run['fencing_token']}", flush=True)
        renew_task = asyncio.create_task(
            _renew_loop(repo, run["id"], owner, run["fencing_token"])
        )
        try:
            final = await execute_run(run, repo, runtime_dir=runtime_dir, model_factory=model_factory)
        except Exception as e:  # noqa: BLE001 — 执行器之外的意外错误也不能拖垮循环
            final = "unexpected"
            if run["attempt"] < run["max_attempts"]:
                await repo.requeue(run["id"], fencing_token=run["fencing_token"],
                                   error=f"worker 意外错误: {type(e).__name__}: {e}")
            else:
                await repo.finish_run(run["id"], fencing_token=run["fencing_token"],
                                      status="failed", attempt=run["attempt"],
                                      error=f"worker 意外错误: {type(e).__name__}: {e}")
        finally:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
        executed += 1
        print(f"[worker:{owner}] done {run['id']} → {final}", flush=True)
        if once:
            break

    await engine.dispose()
    print(f"[worker:{owner}] stopped, executed={executed}", flush=True)
    return 0


async def _renew_loop(repo: RunRepository, run_id: str, owner: str, fencing: int) -> None:
    while True:
        await asyncio.sleep(RENEW_INTERVAL)
        ok = await repo.renew_lease(run_id, owner=owner, fencing_token=fencing)
        if not ok:
            print(f"[worker:{owner}] lease lost on {run_id};结果将被 fencing 拒绝", file=sys.stderr, flush=True)
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fa-worker", description="金融研究 Agent Worker")
    parser.add_argument("--once", action="store_true", help="只执行一个任务后退出(测试/演示)")
    args = parser.parse_args(argv)
    return asyncio.run(run_worker(once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
