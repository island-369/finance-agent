"""M3 测试夹具:临时 SQLite 库、仓储、API 应用(含 lifespan)。"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from finance_agent.adapters.persistence.database import (
    create_engine_factory,
    dispose_engine,
    init_db,
    session_factory,
)
from finance_agent.adapters.persistence.repository import RunRepository


@pytest.fixture()
async def env_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "app.sqlite"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("FINANCE_AGENT_DB_URL", url)
    engine = create_engine_factory(url)
    await init_db(engine)
    await dispose_engine(engine)
    yield db_file


@pytest.fixture()
async def repo(env_db) -> RunRepository:
    engine = create_engine_factory(os.environ["FINANCE_AGENT_DB_URL"])
    await init_db(engine)
    yield RunRepository(session_factory(engine), engine)
    await dispose_engine(engine)


@pytest.fixture()
async def app_client(env_db, tmp_path: Path):
    from finance_agent.interfaces.api.app import create_app

    app = create_app(runtime_dir=tmp_path / "runtime")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
