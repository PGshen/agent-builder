#!/bin/bash
# scheduler 容器只跑一个进程：内嵌 beat 的 Celery worker（-B），既定时扫描又消费自己发出的扫描任务，
# 不需要像 agent-runner 那样再另起一个 HTTP server。
set -e

# -Q scheduler：与 agent-runner 共用同一个 Redis broker，显式限定各自只消费自己的队列，避免互相
# 争抢对方的任务消息（docs/TASKS.md T3.1 决策记录）
exec celery -A app.celery_app worker --beat --loglevel=info -Q scheduler
