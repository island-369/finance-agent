"""M2 离线测试辅助:响应式脚本模型。

M0 的 ScriptedChatModel 只能返回预写消息;结构化结果需要引用工具运行时
生成的 calculation_id(calc-<uuid>),因此这里允许 responses 元素是
callable(messages) -> BaseMessage,按对话历史动态构造最终答复。
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ReactiveScriptedModel(FakeMessagesListChatModel):
    responses: list[Any]

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        item = self.responses[self.i]
        if self.i < len(self.responses) - 1:
            self.i += 1
        msg = item(messages) if callable(item) else item
        return ChatResult(generations=[ChatGeneration(message=msg)])


def read_skill_msg(skill_name: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "read_file",
            "args": {"file_path": f"/skills/{skill_name}/SKILL.md"},
            "id": call_id,
            "type": "tool_call",
        }],
    )


def tool_call_msg(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )


def _find_calc_id(messages) -> str | None:
    for m in reversed(messages):
        if getattr(m, "type", "") == "tool":
            content = m.content
            if isinstance(content, str) and "calculation_id" in content:
                found = re.search(r'"calculation_id":\s*"(calc-[0-9a-f]+)"', content)
                if found:
                    return found.group(1)
    return None


def research_result_msg(objective: str, entity: str):
    """最终结构化结果:calculation_id 引用从工具返回中动态提取(有则引用)。"""

    def build(messages) -> AIMessage:
        calc_id = _find_calc_id(messages)
        args = {
            "objective": objective,
            "researched_at": "2026-10-24T00:00:00+00:00",
            "entity_ids": [entity],
            "summary": "2026H1 净利润同比下降 11.1%(修订口径),收入增长 16.2%,利润率下滑。",
            "key_findings": [
                {
                    "statement": "2026H1 净利润 2.72 亿元,同比下降 11.1%(obs-a-np-cum-2026h1-v2)",
                    "kind": "fact",
                    "refs": ["obs-a-np-cum-2026h1-v2"],
                },
                {
                    "statement": "收入 43.0 亿元同比增长 16.2%,与利润方向相反",
                    "kind": "fact",
                    "refs": ["obs-a-rev-cum-2026h1"],
                },
            ],
            "metric_refs": ["obs-a-np-cum-2026h1-v2", "obs-a-np-cum-2025h1"],
            "calculation_refs": [calc_id] if calc_id else [],
            "evidence_refs": [],
            "information_gaps": ["缺少成本科目,无法定位利润率下滑的具体环节"],
            "skill_versions": ["earnings-analysis@1.0.0"] if calc_id else [],
            "tool_versions": ["finance.get_metrics@1", "finance.calculate_growth@1"] if calc_id else ["finance.get_metrics@1"],
            "quality_flags": [],
        }
        json.dumps(args)  # 确认可序列化
        return tool_call_msg("ResearchResult", args, "call-final")

    return build
