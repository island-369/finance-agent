"""M0 预算跟踪。

设计 §10.4:调用前检查预算、调用后记录真实用量;成本预算是尽力约束,
单次调用可能越过剩余额度,记录超额而不宣称绝对封顶。

计数口径:
- model_calls: 事件流中的 on_chat_model_start(含引擎内部子 Agent 的模型调用)。
- tool_calls:  事件流中的 on_tool_start(含引擎内置工具,如 read_file/task),
  以事件 run_id 去重;金融工具包装器在执行前用同一计数做预检查。

M0 已知缺口(如实记录,不视为已完成):
- 预算计数仅在事件观察侧累计,恢复执行时从 0 重新计数(设计要求沿用已消耗计数)。
- 事件与工具执行并发时的计数时序不提供严格"恰好一次"保证。
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetAbort(Exception):
    """预算越界,执行侧主动放弃继续消费事件流。"""


@dataclass
class Budget:
    max_model_calls: int = 15
    max_tool_calls: int = 30
    model_calls: int = 0
    tool_calls: int = 0
    _seen_tool_runs: set[str] = field(default_factory=set, repr=False)

    def check_model(self) -> None:
        if self.model_calls >= self.max_model_calls:
            raise BudgetAbort(f"model_calls {self.model_calls} >= {self.max_model_calls}")

    def record_model(self) -> None:
        self.model_calls += 1

    def check_tool(self) -> bool:
        """工具执行前的预检查;返回 False 表示应拒绝本次调用。"""
        return self.tool_calls < self.max_tool_calls

    def record_tool(self, run_id: str | None = None) -> bool:
        """记录一次工具调用;run_id 提供时按事件 run_id 去重。

        返回是否为首次记录(去重命中返回 False)。
        """
        if run_id is not None:
            if run_id in self._seen_tool_runs:
                return False
            self._seen_tool_runs.add(run_id)
        self.tool_calls += 1
        return True

    def snapshot(self) -> dict:
        return {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
        }
