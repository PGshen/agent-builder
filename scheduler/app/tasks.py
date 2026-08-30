"""周期扫描任务：判断哪些 Agent 到期该刷新绑定仓库了，逐个按需派发。

派发的任务名 `"workspace.refresh_repos"`、参数 `args=[agent_id]`（str）是 T3.1 定的契约（docs/TASKS.md
T3.1 决策记录），T3.2 落地时 Runner 侧要注册同名任务消费。本服务只发不消费，与 backend-api
`app/modules/agents/tasks.py::trigger_workspace_init` 是同样的"生产者"角色。
"""

from datetime import UTC, datetime

from app.celery_app import celery_app
from app.db import fetch_ready_agents_repo_sync_status
from app.dispatch_lock import try_acquire_dispatch_lock
from app.due import is_due
from app.logging_config import get_logger

logger = get_logger(__name__)

WORKSPACE_REFRESH_TASK_NAME = "workspace.refresh_repos"


@celery_app.task(name="scheduler.scan_due_agents")
def scan_due_agents() -> int:
    """返回本轮实际派发的任务数（供日志/手动验证用，非任务契约的一部分）。"""

    import asyncio

    statuses = asyncio.run(fetch_ready_agents_repo_sync_status())
    now = datetime.now(UTC)

    dispatched = 0
    for status in statuses:
        if not is_due(status, now):
            continue

        agent_id = str(status.agent_id)
        if not try_acquire_dispatch_lock(agent_id):
            logger.info("scheduler_dispatch_skipped_locked", agent_id=agent_id)
            continue

        # queue="agent-runner"：与 backend-api 的 workspace.init 走同一条路由约定，显式发到 Runner
        # 专属队列，避免 scheduler 自己的 worker 把这条任务又消费回自己那边
        celery_app.send_task(WORKSPACE_REFRESH_TASK_NAME, args=[agent_id], queue="agent-runner")
        logger.info("scheduler_dispatch_refresh", agent_id=agent_id)
        dispatched += 1

    return dispatched
