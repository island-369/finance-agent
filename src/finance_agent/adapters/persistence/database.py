"""数据库连接与初始化。

URL 来自 FINANCE_AGENT_DB_URL;默认本地 SQLite,Compose 部署指向 PostgreSQL
(postgresql+psycopg://...,psycopg3 同步/异步两用,Alembic 迁移用同步引擎)。
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from finance_agent.adapters.persistence.models import Base

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./data/runtime/app.sqlite"


def db_url() -> str:
    url = os.environ.get("FINANCE_AGENT_DB_URL", DEFAULT_SQLITE_URL)
    return url


def sync_db_url() -> str:
    """Alembic 迁移用的同步 URL(驱动替换:aio 驱动 → 同步驱动)。"""
    url = db_url()
    if url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite+aiosqlite", "sqlite", 1)
    if url.startswith("postgresql+psycopg"):
        return url  # psycopg3 同步可用
    return url


def create_engine_factory(url: str | None = None) -> AsyncEngine:
    target = url or db_url()
    if target.startswith("sqlite"):
        Path(_sqlite_path(target)).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(target, echo=False)


def _sqlite_path(url: str) -> str:
    # sqlite+aiosqlite:///./path
    return url.split("///", 1)[1] if "///" in url else ":memory:"


def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """测试/本地快速建表;正式部署用 Alembic(见 migrations/)。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            # SQLite 的 JSON 列以文本存储;WAL 提高读写并发
            await conn.execute(text("PRAGMA journal_mode=WAL"))


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
