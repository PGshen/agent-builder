"""到期判断要用到的 Postgres 读取。

不引入 SQLAlchemy ORM（沿用 agent-runner `app/workspace/db.py` 已经定的先例——scheduler 也只是
消费方，字段名与 backend-api `app/modules/agents/models.py` 表结构保持一致即可），`asyncpg` 原生连接 + 手写 SQL。
"""

import uuid
from dataclasses import dataclass

import asyncpg

from app.config import get_settings


@dataclass
class AgentRepoSyncStatus:
    agent_id: uuid.UUID
    repo_refresh_interval_minutes: int
    min_last_synced_at: "object | None"  # datetime | None，避免在这层强依赖 datetime 类型细节


async def fetch_ready_agents_repo_sync_status() -> list[AgentRepoSyncStatus]:
    """返回所有 status='ready' 且绑定了至少一个仓库的 Agent，及其名下仓库最早一次成功同步时间（MIN）。"""

    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT
                a.id AS agent_id,
                a.repo_refresh_interval_minutes AS repo_refresh_interval_minutes,
                MIN(r.last_synced_at) AS min_last_synced_at
            FROM agents a
            JOIN agent_repositories r ON r.agent_id = a.id
            WHERE a.status = 'ready'
            GROUP BY a.id, a.repo_refresh_interval_minutes
            """
        )
        return [
            AgentRepoSyncStatus(
                agent_id=row["agent_id"],
                repo_refresh_interval_minutes=row["repo_refresh_interval_minutes"],
                min_last_synced_at=row["min_last_synced_at"],
            )
            for row in rows
        ]
    finally:
        await conn.close()
