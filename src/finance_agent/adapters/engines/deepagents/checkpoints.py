"""M2 检查点存储(SQLite;M3 迁移 PostgreSQL 独立命名空间)。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from finance_agent.contracts.result import ResearchResult

_ALLOWED_TYPES = [ResearchResult]


@asynccontextmanager
async def open_sqlite_saver(db_path: Path) -> AsyncIterator:
    import aiosqlite
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        yield AsyncSqliteSaver(
            conn, serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_TYPES)
        )
