"""M0 模型工厂:OpenAI 兼容端点(默认智谱 GLM)。

设计 §13.2:模型与供应商由已登记配置选择,不接受请求上传秘钥。
秘钥只从环境/.env 读取,不进入日志。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.6"


class MissingApiKeyError(RuntimeError):
    pass


def build_chat_model() -> ChatOpenAI:
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise MissingApiKeyError(
            "未检测到 OPENAI_API_KEY。复制 .env.example 为 .env 并填入秘钥;"
            "无秘钥时可运行 `uv run m0 check` 执行离线兼容性检查。"
        )
    # DeepSeek 思考模式不支持强制 tool_choice(引擎 ToolStrategy 依赖它提交结构化
    # 结果),因此默认关闭思考;FINANCE_AGENT_THINKING=enabled 可重新打开。
    thinking_type = os.environ.get("FINANCE_AGENT_THINKING", "disabled")
    return ChatOpenAI(
        model=os.environ.get("FINANCE_AGENT_MODEL", DEFAULT_MODEL),
        api_key=api_key,
        base_url=os.environ.get("FINANCE_AGENT_BASE_URL", DEFAULT_BASE_URL),
        # 兼容端点走 chat completions,不使用 OpenAI Responses API
        use_responses_api=False,
        temperature=0.2,
        max_retries=2,
        extra_body={"thinking": {"type": thinking_type}},
    )
