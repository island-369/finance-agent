"""数据源与存储接口(设计 §15 ports 模块)。

核心模块依赖接口;具体实现(fixture、真实供应商、PostgreSQL)在
adapters/data 提供,由 bootstrap 装配注入。
"""

from finance_agent.ports.data import DocumentSource, MetricSource

__all__ = ["DocumentSource", "MetricSource"]
