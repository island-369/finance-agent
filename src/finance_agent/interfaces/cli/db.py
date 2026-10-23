"""数据库 CLI:初始化/迁移。

用法:
    fa-db upgrade     # 建表(本地 SQLite 默认;PostgreSQL 用 FINANCE_AGENT_DB_URL)
"""

from __future__ import annotations

import argparse
import asyncio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fa-db", description="数据库初始化")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("upgrade", help="建表(等价 metadata.create_all)")
    parser.parse_args(argv)

    from finance_agent.adapters.persistence.database import (
        create_engine_factory,
        dispose_engine,
        init_db,
    )

    async def _run():
        engine = create_engine_factory()
        await init_db(engine)
        await dispose_engine(engine)

    asyncio.run(_run())
    print("数据库已就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
