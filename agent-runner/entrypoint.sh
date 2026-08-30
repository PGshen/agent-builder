#!/bin/bash
# Runner 容器同时承担两类角色（TECH_DESIGN 3）：Celery worker（后台任务）+ 流式执行 HTTP 服务。
# 任一进程退出，整个容器退出，交给编排层重启，避免"看起来活着但少了一半功能"的假健康状态。
set -e

PORT="${AGENT_RUNNER_HTTP_PORT:-8100}"

# -Q agent-runner：scheduler（T3.1）也是一个 Celery worker，共用同一个 Redis broker；不显式限定
# 队列的话，两边 worker 会争抢同一个默认队列 "celery" 里彼此的任务，导致消息被不认识的一方悄悄丢弃
# （Runner 消息路由约定见 docs/TASKS.md T3.1 决策记录）
celery -A app.worker.celery_app worker --loglevel=info -Q agent-runner &
CELERY_PID=$!

uvicorn app.server.main:app --host 0.0.0.0 --port "$PORT" &
UVICORN_PID=$!

trap 'kill -TERM $CELERY_PID $UVICORN_PID 2>/dev/null' TERM INT

wait -n "$CELERY_PID" "$UVICORN_PID"
EXIT_CODE=$?
kill "$CELERY_PID" "$UVICORN_PID" 2>/dev/null || true
exit "$EXIT_CODE"
