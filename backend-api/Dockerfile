FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh ./
RUN uv sync --locked --no-dev && chmod +x entrypoint.sh

EXPOSE 8080

# 容器启动先 `alembic upgrade head` 把 schema 应用到最新，再起 uvicorn，保证各环境 schema 一致
CMD ["./entrypoint.sh"]
