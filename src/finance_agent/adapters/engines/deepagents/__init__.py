"""Deep Agents 引擎适配器。

职责(设计 §9.3):把 ToolRegistry 中的工具转换成引擎要求的调用格式,
接入 Skill 中间件(只读视图),执行事件流并产出执行记录。
金融工具的名称映射、结构化错误与预算预检查都在这里 bridging;
核心模块(contracts/finance/tools/skills)不感知本包。
"""
