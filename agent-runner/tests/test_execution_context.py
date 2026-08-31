"""用真实本地 Postgres 验证 `execution/context.py` 的 JOIN 查询（agent_skills/agent_mcp_servers
关联表 + workspace_snapshots），而不是像 `test_sessions_store.py` 那样搭一个 fake asyncpg 连接——
这里的 SQL 涉及多表 JOIN，用 fake 连接只能验证"调用了某个 SQL 字符串"，验证不了 JOIN 结果是否正确，
真实数据库反而是更省事、更可信的验证方式。需要本地 `docker compose up -d postgres`（已在其它 T4.x/T2.x
任务的验证过程中确认可用）。
"""

import uuid

import asyncpg
import pytest

from app.config import get_settings
from app.execution import context as context_module


@pytest.fixture
async def db_conn():
    conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def _make_agent(conn, *, status: str = "ready") -> uuid.UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO agents (name, workspace_id, permission_mode, status, repo_refresh_interval_minutes)
        VALUES ($1, $2, 'acceptEdits', $3, 30)
        RETURNING id
        """,
        f"test-agent-{uuid.uuid4().hex[:8]}",
        "ws-" + uuid.uuid4().hex,
        status,
    )
    return row["id"]


async def _make_skill(conn, name: str) -> uuid.UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO skills (name, object_key, version, active_version, versions, status)
        VALUES ($1, $2, 1, 1, '[]'::jsonb, 'active')
        RETURNING id
        """,
        name,
        f"{uuid.uuid4()}/v1.zip",
    )
    return row["id"]


async def _make_mcp_server(conn, name: str) -> uuid.UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO mcp_servers (name, config_encrypted, status)
        VALUES ($1, 'ciphertext', 'active')
        RETURNING id
        """,
        name,
    )
    return row["id"]


@pytest.fixture
async def cleanup(db_conn):
    agent_ids: list[uuid.UUID] = []
    skill_ids: list[uuid.UUID] = []
    mcp_ids: list[uuid.UUID] = []
    yield agent_ids, skill_ids, mcp_ids
    for agent_id in agent_ids:
        await db_conn.execute("DELETE FROM agents WHERE id = $1", agent_id)
    for skill_id in skill_ids:
        await db_conn.execute("DELETE FROM skills WHERE id = $1", skill_id)
    for mcp_id in mcp_ids:
        await db_conn.execute("DELETE FROM mcp_servers WHERE id = $1", mcp_id)


async def test_load_execution_context_raises_when_agent_missing():
    with pytest.raises(context_module.AgentNotReadyError):
        await context_module.load_execution_context(uuid.uuid4())


async def test_load_execution_context_raises_when_agent_not_ready(db_conn, cleanup):
    agent_ids, _, _ = cleanup
    agent_id = await _make_agent(db_conn, status="initializing")
    agent_ids.append(agent_id)

    with pytest.raises(context_module.AgentNotReadyError):
        await context_module.load_execution_context(agent_id)


async def test_load_execution_context_raises_when_workspace_snapshot_missing(db_conn, cleanup):
    agent_ids, _, _ = cleanup
    agent_id = await _make_agent(db_conn, status="ready")
    agent_ids.append(agent_id)

    with pytest.raises(context_module.AgentNotReadyError):
        await context_module.load_execution_context(agent_id)


async def test_load_execution_context_returns_bound_skills_and_mcp_servers(db_conn, cleanup):
    agent_ids, skill_ids, mcp_ids = cleanup
    agent_id = await _make_agent(db_conn, status="ready")
    agent_ids.append(agent_id)
    skill_id = await _make_skill(db_conn, "skill-" + uuid.uuid4().hex[:8])
    skill_ids.append(skill_id)
    mcp_id = await _make_mcp_server(db_conn, "mcp-" + uuid.uuid4().hex[:8])
    mcp_ids.append(mcp_id)

    await db_conn.execute(
        "INSERT INTO agent_skills (agent_id, skill_id) VALUES ($1, $2)", agent_id, skill_id
    )
    await db_conn.execute(
        "INSERT INTO agent_mcp_servers (agent_id, mcp_server_id) VALUES ($1, $2)", agent_id, mcp_id
    )
    await db_conn.execute(
        """
        INSERT INTO workspace_snapshots (
            agent_id, repo_snapshot_object_key, repo_snapshot_version, repo_snapshot_updated_at,
            output_snapshot_object_key, output_snapshot_version, output_snapshot_updated_at,
            output_snapshot_update_source
        ) VALUES ($1, 'repo-key', 1, now(), 'output-key', 1, now(), 'workspace_init')
        """,
        agent_id,
    )

    context = await context_module.load_execution_context(agent_id)

    assert context.permission_mode == "acceptEdits"
    assert context.repo_snapshot_object_key == "repo-key"
    assert context.output_snapshot_object_key == "output-key"
    assert [s.id for s in context.skills] == [skill_id]
    assert [m.id for m in context.mcp_servers] == [mcp_id]


async def test_save_output_snapshot_updates_workspace_snapshot_row(db_conn, cleanup):
    agent_ids, _, _ = cleanup
    agent_id = await _make_agent(db_conn, status="ready")
    agent_ids.append(agent_id)
    await db_conn.execute(
        """
        INSERT INTO workspace_snapshots (
            agent_id, repo_snapshot_version, output_snapshot_object_key, output_snapshot_version,
            output_snapshot_updated_at, output_snapshot_update_source
        ) VALUES ($1, 0, 'old-key', 1, now(), 'workspace_init')
        """,
        agent_id,
    )

    await context_module.save_output_snapshot(agent_id, "new-key", 2, "conversation_sync")

    row = await db_conn.fetchrow(
        "SELECT output_snapshot_object_key, output_snapshot_version, output_snapshot_update_source "
        "FROM workspace_snapshots WHERE agent_id = $1",
        agent_id,
    )
    assert row["output_snapshot_object_key"] == "new-key"
    assert row["output_snapshot_version"] == 2
    assert row["output_snapshot_update_source"] == "conversation_sync"
