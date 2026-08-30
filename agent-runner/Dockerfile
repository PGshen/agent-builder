FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# git（clone 绑定仓库）+ openssh-client（ssh_key 鉴权方式的仓库需要 ssh 命令）+ ca-certificates（https 仓库 TLS 校验）
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY entrypoint.sh ./entrypoint.sh
RUN uv sync --locked --no-dev && chmod +x entrypoint.sh

EXPOSE 8100

ENTRYPOINT ["./entrypoint.sh"]
