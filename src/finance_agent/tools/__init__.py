"""工具模块:注册中心与工具实现。

不依赖特定模型的消息对象(设计 §5);调用约束(schema 校验、预算、
错误结构化)在注册中心统一执行,工具处理函数保持纯业务逻辑。
"""

from finance_agent.tools.registry import ToolRegistry

__all__ = ["ToolRegistry"]
