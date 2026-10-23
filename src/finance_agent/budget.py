"""预算跟踪(设计 §10.4)。

调用前检查预算、调用后记录真实用量;越界的调用既已发出就如实计数,
记录超额而不宣称绝对封顶。

计数口径:
- model_calls: 事件流中的 on_chat_model_start(含引擎内部子 Agent 的模型调用)。
- tool_calls:  事件流中的 on_tool_start(含引擎内置工具,如 read_file),
  以事件 run_id 去重;工具注册中心的 TaskContext.budget_check 做执行前预检查。

M2+ 的规范位置;M0 实验代码经 m0/budget.py 的再导出继续使用同一实现。
已知缺口(待 M3):恢复执行时计数不持久化,从零重新计数。
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
        """记录一次工具调用;run_id 提供时按事件 run_id 去重。"""
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

    @classmethod
    def from_snapshot(cls, data: dict) -> Budget:
        """从持久化的预算快照恢复(§10.4:恢复沿用已消耗计数,不重置)。"""
        return cls(
            max_model_calls=data.get("max_model_calls", 15),
            max_tool_calls=data.get("max_tool_calls", 30),
            model_calls=data.get("model_calls", 0),
            tool_calls=data.get("tool_calls", 0),
        )
