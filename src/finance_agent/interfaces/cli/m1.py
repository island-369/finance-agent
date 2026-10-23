"""M1 CLI:五个核心工具脱离 Agent 单独调用(设计 §17 M1 退出条件)。

用法:
    uv run m1 tools
    uv run m1 call finance.get_metrics '{"entity_id":"demo-company-a","metric":"net_profit"}'
    uv run m1 call documents.search '{"query":"净利润 更正"}' --as-of 2026-05-01T00:00:00+00:00
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from finance_agent.bootstrap import build_default_registry
from finance_agent.contracts.task import TaskContext

DEFAULT_AS_OF = "2026-08-31T23:59:59+08:00"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m1", description="M1 金融契约与离线工具 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tools", help="列出已注册工具")

    p_call = sub.add_parser("call", help="单独调用一个工具")
    p_call.add_argument("name", help="工具名,如 finance.get_metrics")
    p_call.add_argument("args", help="JSON 参数")
    p_call.add_argument("--as-of", default=DEFAULT_AS_OF, help="任务截止时间(默认 2026-08-31 23:59:59 +08:00)")

    args = parser.parse_args(argv)
    registry = build_default_registry()

    if args.command == "tools":
        for spec in registry.list_tools():
            print(json.dumps(spec.describe(), ensure_ascii=False, indent=2))
        return 0

    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as e:
        print(f"参数不是合法 JSON: {e}", file=sys.stderr)
        return 2

    ctx = TaskContext(as_of=datetime.fromisoformat(args.as_of))
    result = registry.call(args.name, tool_args, ctx)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
