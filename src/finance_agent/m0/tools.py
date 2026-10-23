"""M0 金融工具:标准化财务观测查询。

验证设计 §8 的最小子集:
- 结构化错误(§8.5):INVALID_ARGUMENT / DATA_NOT_FOUND / TIME_BOUNDARY_VIOLATION /
  BUDGET_EXCEEDED,错误带原因与可行替代动作,不抛裸异常打断 Agent 循环。
- 时间边界(§8.4):任务 as_of 由执行端注入,模型传入更晚的 as_of 会被拒绝;
  修订数据取截止时间内可获得的最新版本。
- 预算预检查(§10.4):工具执行前检查剩余额度。

M0 只做一个查询工具;calculate_growth / compare_peers 等计算类工具属 M1 范围。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from langchain_core.tools import BaseTool, tool

from finance_agent.m0.budget import Budget

TIME_BOUNDARY_VIOLATION = "TIME_BOUNDARY_VIOLATION"
DATA_NOT_FOUND = "DATA_NOT_FOUND"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


def tool_error(code: str, message: str, **extra: Any) -> str:
    payload = {"error": {"code": code, "message": message, "retriable": False, **extra}}
    return json.dumps(payload, ensure_ascii=False)


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed


def make_finance_get_metrics_tool(
    observations: list[dict],
    budget: Budget,
    task_as_of: datetime,
) -> BaseTool:
    """构造 finance.get_metrics@1 的 M0 版本。

    task_as_of 以闭包方式注入(执行端约束),不依赖模型自觉。
    """

    @tool("finance_get_metrics")
    def finance_get_metrics(
        entity_id: str,
        metric: str,
        as_of: str | None = None,
    ) -> str:
        """查询标准化财务观测(累计口径)。返回 available_at 不晚于 as_of 的最新修订版本。

        Args:
            entity_id: 公司标识,如 demo-company-a
            metric: 指标名,revenue(营业收入)或 net_profit(净利润)
            as_of: 可选的截止时间(ISO 8601)。缺省使用任务截止时间;不得晚于任务截止时间。
        """
        if not budget.check_tool():
            return tool_error(
                BUDGET_EXCEEDED,
                f"工具调用预算已用尽({budget.tool_calls}/{budget.max_tool_calls})",
                fallback="直接基于已获得的观测给出部分结论,并说明信息缺口。",
            )
        try:
            effective_as_of = _parse_as_of(as_of) if as_of else task_as_of
        except ValueError:
            return tool_error(INVALID_ARGUMENT, f"as_of 不是合法的 ISO 8601 时间: {as_of!r}")

        if effective_as_of > task_as_of:
            return tool_error(
                TIME_BOUNDARY_VIOLATION,
                f"请求的 as_of({effective_as_of.isoformat()})晚于任务截止时间"
                f"({task_as_of.isoformat()}),不允许扩大截止时间。",
                fallback="改用不晚于任务截止时间的 as_of,或省略该参数。",
            )

        matched = [
            o
            for o in observations
            if o["entity_id"] == entity_id
            and o["metric"] == metric
            and _parse_as_of(o["available_at"]) <= effective_as_of
        ]
        if not matched:
            available_entities = sorted({o["entity_id"] for o in observations})
            return tool_error(
                DATA_NOT_FOUND,
                f"截止 {effective_as_of.isoformat()} 没有可获得的观测:"
                f"entity_id={entity_id!r}, metric={metric!r}。",
                tried=f"entity_id={entity_id!r}, metric={metric!r}",
                available_entities=available_entities,
                available_metrics=sorted({o["metric"] for o in observations}),
            )

        # 同一报告期可能存在多版本修订:取 available_at 最新的版本(仍不得晚于 as_of)
        latest_by_period: dict[str, dict] = {}
        for o in matched:
            key = o["period_end"]
            if key not in latest_by_period or _parse_as_of(o["available_at"]) > _parse_as_of(
                latest_by_period[key]["available_at"]
            ):
                latest_by_period[key] = o

        ordered = sorted(latest_by_period.values(), key=lambda o: o["period_end"])
        return json.dumps(
            {
                "entity_id": entity_id,
                "metric": metric,
                "as_of_effective": effective_as_of.isoformat(),
                "observation_count": len(ordered),
                "note": "数值为合成样本,仅用于工程验证。",
                "observations": ordered,
            },
            ensure_ascii=False,
        )

    return finance_get_metrics
