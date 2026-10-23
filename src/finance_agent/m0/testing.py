"""M0 离线测试辅助:可脚本化的假模型。

FakeMessagesListChatModel 的 bind_tools 是 NotImplementedError;Agent 循环
绑定工具(业务工具 + ToolStrategy 结构化输出工具)时会失败。这里覆写为
忽略绑定、按脚本顺序返回消息——工具调用已写死在脚本消息里,与真实模型
路径共用同一套图执行逻辑。
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel


class ScriptedChatModel(FakeMessagesListChatModel):
    """按 responses 顺序循环返回消息,忽略工具绑定与结构化参数。"""

    def bind_tools(self, tools, **kwargs):
        return self
