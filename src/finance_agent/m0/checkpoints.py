"""M0 检查点存储辅助。

SqliteSaver 默认序列化器在反序列化自定义 Pydantic 类型(如结构化结果)时
只警告不阻止,未来版本会直接拒绝。这里显式构造带类型允许清单的序列化器,
保证跨进程恢复(m0 run / m0 resume)不受影响。

设计 §10.2:M0 与应用数据库共用本机 SQLite 文件只是实验形态;
M3 将换成独立表/命名空间并接入 PostgreSQL。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from finance_agent.m0.result import M0ResearchResult

# 结构化结果与后续自定义状态类型都注册在此,恢复时才能安全解码
_ALLOWED_TYPES = [M0ResearchResult]


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
