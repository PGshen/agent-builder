"""T4.3 流式执行接口用到的执行期上下文：从 Postgres 读出一次执行需要的全部 Agent 配置
（workspace 快照版本、绑定的 skills/MCP、权限模式），供 `workspace_cache`/`sdk_options` 使用。

沿用 `app/workspace/db.py` 已建立的模式：不引入 ORM，`asyncpg` 原生连接 + 手写 SQL，字段名
与 backend-api 对应模块的表结构保持一致。
"""

import uuid
from dataclasses import dataclass, field

import asyncpg

from app.config import get_settings


class AgentNotReadyError(Exception):
    """Agent 不存在，或 workspace 尚未初始化完成（`status != "ready"`）——这种情况下不具备执行条件，
    调用方应该给出明确反馈，而不是让 SDK 调用在一个不完整/不存在的工作目录里跑起来。"""

    def __init__(self, agent_id: uuid.UUID, reason: str):
        self.agent_id = agent_id
        self.reason = reason
        super().__init__(reason)


@dataclass
class SkillRef:
    id: uuid.UUID
    name: str
    object_key: str
    version: int


@dataclass
class MCPServerRef:
    id: uuid.UUID
    name: str
    config_encrypted: str


@dataclass
class ExecutionContext:
    agent_id: uuid.UUID
    workspace_id: str
    permission_mode: str
    repo_snapshot_object_key: str | None
    repo_snapshot_version: int
    output_snapshot_object_key: str | None
    output_snapshot_version: int
    skills: list[SkillRef] = field(default_factory=list)
    mcp_servers: list[MCPServerRef] = field(default_factory=list)


async def load_execution_context(agent_id: uuid.UUID) -> ExecutionContext:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        agent_row = await conn.fetchrow(
            "SELECT id, workspace_id, permission_mode, status FROM agents WHERE id = $1", agent_id
        )
        if agent_row is None:
            raise AgentNotReadyError(agent_id, "Agent 不存在")
        if agent_row["status"] != "ready":
            raise AgentNotReadyError(agent_id, f"Agent 当前状态是 {agent_row['status']}，尚未就绪，无法执行")

        snapshot_row = await conn.fetchrow(
            """
            SELECT repo_snapshot_object_key, repo_snapshot_version,
                   output_snapshot_object_key, output_snapshot_version
            FROM workspace_snapshots WHERE agent_id = $1
            """,
            agent_id,
        )
        if snapshot_row is None or snapshot_row["output_snapshot_object_key"] is None:
            raise AgentNotReadyError(agent_id, "Agent 尚未完成 workspace 初始化")

        skill_rows = await conn.fetch(
            """
            SELECT s.id, s.name, s.object_key, s.version
            FROM agent_skills a
            JOIN skills s ON s.id = a.skill_id
            WHERE a.agent_id = $1 AND s.status = 'active'
            ORDER BY s.name
            """,
            agent_id,
        )
        mcp_rows = await conn.fetch(
            """
            SELECT m.id, m.name, m.config_encrypted
            FROM agent_mcp_servers a
            JOIN mcp_servers m ON m.id = a.mcp_server_id
            WHERE a.agent_id = $1 AND m.status = 'active'
            ORDER BY m.name
            """,
            agent_id,
        )

        return ExecutionContext(
            agent_id=agent_row["id"],
            workspace_id=agent_row["workspace_id"],
            permission_mode=agent_row["permission_mode"],
            repo_snapshot_object_key=snapshot_row["repo_snapshot_object_key"],
            repo_snapshot_version=snapshot_row["repo_snapshot_version"],
            output_snapshot_object_key=snapshot_row["output_snapshot_object_key"],
            output_snapshot_version=snapshot_row["output_snapshot_version"],
            skills=[SkillRef(**dict(row)) for row in skill_rows],
            mcp_servers=[MCPServerRef(**dict(row)) for row in mcp_rows],
        )
    finally:
        await conn.close()


async def save_output_snapshot(
    agent_id: uuid.UUID, object_key: str, version: int, update_source: str
) -> None:
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        await conn.execute(
            """
            UPDATE workspace_snapshots
            SET output_snapshot_object_key = $2, output_snapshot_version = $3,
                output_snapshot_updated_at = now(), output_snapshot_update_source = $4
            WHERE agent_id = $1
            """,
            agent_id,
            object_key,
            version,
            update_source,
        )
    finally:
        await conn.close()
