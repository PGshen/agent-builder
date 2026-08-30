"""Workspace 初始化任务用到的 Postgres 读写。

Runner 侧不引入 SQLAlchemy ORM（那是 backend-api 的模型定义/迁移职责，Runner 只是消费方，
两边各自维护一套 ORM 模型会带来同步负担）；沿用 `app/server/health.py` 已经建立的模式——
`asyncpg` 原生连接 + 手写 SQL，字段名与 backend-api `app/modules/agents/models.py` 的表结构
保持一致即可，不需要额外的模型映射层。
"""

import uuid
from dataclasses import dataclass, field

import asyncpg

from app.config import get_settings


@dataclass
class RepositoryRecord:
    id: uuid.UUID
    url: str
    branch: str | None
    auth_type: str
    auth_credential: str | None
    position: int


@dataclass
class AgentInitContext:
    agent_id: uuid.UUID
    workspace_id: str
    repositories: list[RepositoryRecord] = field(default_factory=list)
    repo_snapshot_version: int = 0
    output_snapshot_version: int = 0


async def load_agent_context(agent_id: uuid.UUID) -> AgentInitContext | None:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        agent_row = await conn.fetchrow(
            "SELECT id, workspace_id FROM agents WHERE id = $1", agent_id
        )
        if agent_row is None:
            return None

        repo_rows = await conn.fetch(
            """
            SELECT id, url, branch, auth_type, auth_credential, position
            FROM agent_repositories
            WHERE agent_id = $1
            ORDER BY position
            """,
            agent_id,
        )
        snapshot_row = await conn.fetchrow(
            """
            SELECT repo_snapshot_version, output_snapshot_version
            FROM workspace_snapshots
            WHERE agent_id = $1
            """,
            agent_id,
        )

        return AgentInitContext(
            agent_id=agent_row["id"],
            workspace_id=agent_row["workspace_id"],
            repositories=[RepositoryRecord(**dict(row)) for row in repo_rows],
            repo_snapshot_version=snapshot_row["repo_snapshot_version"] if snapshot_row else 0,
            output_snapshot_version=snapshot_row["output_snapshot_version"] if snapshot_row else 0,
        )
    finally:
        await conn.close()


async def mark_agent_status(agent_id: uuid.UUID, status: str, status_message: str | None) -> None:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        await conn.execute(
            "UPDATE agents SET status = $2, status_message = $3, updated_at = now() WHERE id = $1",
            agent_id,
            status,
            status_message,
        )
    finally:
        await conn.close()


async def save_workspace_snapshot(
    agent_id: uuid.UUID,
    repo_snapshot_object_key: str,
    repo_snapshot_version: int,
    output_snapshot_object_key: str,
    output_snapshot_version: int,
    output_snapshot_update_source: str,
) -> None:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        await conn.execute(
            """
            INSERT INTO workspace_snapshots (
                agent_id,
                repo_snapshot_object_key, repo_snapshot_version, repo_snapshot_updated_at,
                output_snapshot_object_key, output_snapshot_version, output_snapshot_updated_at,
                output_snapshot_update_source
            ) VALUES ($1, $2, $3, now(), $4, $5, now(), $6)
            ON CONFLICT (agent_id) DO UPDATE SET
                repo_snapshot_object_key = EXCLUDED.repo_snapshot_object_key,
                repo_snapshot_version = EXCLUDED.repo_snapshot_version,
                repo_snapshot_updated_at = EXCLUDED.repo_snapshot_updated_at,
                output_snapshot_object_key = EXCLUDED.output_snapshot_object_key,
                output_snapshot_version = EXCLUDED.output_snapshot_version,
                output_snapshot_updated_at = EXCLUDED.output_snapshot_updated_at,
                output_snapshot_update_source = EXCLUDED.output_snapshot_update_source
            """,
            agent_id,
            repo_snapshot_object_key,
            repo_snapshot_version,
            output_snapshot_object_key,
            output_snapshot_version,
            output_snapshot_update_source,
        )
    finally:
        await conn.close()


async def update_repository_sync_info(repo_id: uuid.UUID, commit: str) -> None:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        await conn.execute(
            "UPDATE agent_repositories SET last_synced_at = now(), last_synced_commit = $2 WHERE id = $1",
            repo_id,
            commit,
        )
    finally:
        await conn.close()
