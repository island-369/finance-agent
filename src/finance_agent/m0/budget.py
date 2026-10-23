"""M0 兼容层:预算实现的规范位置已移至 finance_agent.budget(M2 起)。"""

from finance_agent.budget import Budget, BudgetAbort

__all__ = ["Budget", "BudgetAbort"]
