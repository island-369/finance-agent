# 金融研究 Agent(API 与 Worker 共用镜像)
FROM python:3.12-slim

# uv 安装依赖(uv.lock 固定版本);运行时只装主依赖组
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# 先拷依赖清单以利用层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷源码与运行资源(Skill 包参与构建视图)
COPY src/ src/
COPY skills/ skills/
COPY README.md ./
RUN uv sync --frozen --no-dev

ENV FINANCE_AGENT_RUNTIME_DIR=/app/data/runtime
VOLUME ["/app/data/runtime"]

# 默认 API;Worker 由 compose 覆盖 command 为 fa-worker
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "finance_agent.interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
