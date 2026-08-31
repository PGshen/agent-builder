"""Claude Agent SDK `SessionStore` 接口的 Postgres adapter（T4.1）。

严格按 SDK 定义的 `SessionStore` Protocol 实现（duck-typed，不要求继承）：`append`/`load` 是必需方法，
`list_sessions`/`delete`/`list_subkeys` 是可选方法（SDK 在调用前用 `hasattr` 探测是否存在，未实现的方法
不应该出现在类上，而不是定义后 `raise NotImplementedError`——否则会被探测为"已实现"）。
`list_session_summaries` 依赖 SDK 内部的 `fold_session_summary` 帮助函数维护增量摘要，v1 不实现
（对话列表页 T5.1 需要摘要时再补）。

SDK 的 `SessionKey` 是 `{project_key, session_id, subpath}` 三元组，`sdk_sessions` 表以此为复合主键
（见 T1.1 之后 T4.1 的 schema 修正，`docs/TASKS.md` T4.1 决策记录）。`agent_id` 是 adapter 实例化时由
调用方（T4.3 的执行流程）传入的，与 `project_key` 的取值含义无关，只用于 FK 级联删除。
"""

from __future__ import annotations

import json
import time
import uuid

import asyncpg
from claude_agent_sdk import (
    SessionKey,
    SessionListSubkeysKey,
    SessionStoreEntry,
    SessionStoreListEntry,
)

from app.config import get_settings


class PostgresSessionStore:
    """一个 Agent 一个 adapter 实例，`agent_id` 在构造时固定。"""

    def __init__(self, agent_id: uuid.UUID):
        self._agent_id = agent_id

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        if not entries:
            return
        subpath = key.get("subpath", "")
        conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT entries FROM sdk_sessions
                    WHERE project_key = $1 AND session_id = $2 AND subpath = $3
                    FOR UPDATE
                    """,
                    key["project_key"],
                    key["session_id"],
                    subpath,
                )
                existing: list[SessionStoreEntry] = json.loads(row["entries"]) if row is not None else []
                merged = _merge_entries(existing, entries)
                now_ms = int(time.time() * 1000)
                await conn.execute(
                    """
                    INSERT INTO sdk_sessions (project_key, session_id, subpath, agent_id, entries, mtime_ms)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    ON CONFLICT (project_key, session_id, subpath)
                    DO UPDATE SET entries = EXCLUDED.entries, mtime_ms = EXCLUDED.mtime_ms
                    """,
                    key["project_key"],
                    key["session_id"],
                    subpath,
                    self._agent_id,
                    json.dumps(merged),
                    now_ms,
                )
        finally:
            await conn.close()

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
        try:
            row = await conn.fetchrow(
                """
                SELECT entries FROM sdk_sessions
                WHERE project_key = $1 AND session_id = $2 AND subpath = $3
                """,
                key["project_key"],
                key["session_id"],
                key.get("subpath", ""),
            )
        finally:
            await conn.close()
        if row is None:
            return None
        return json.loads(row["entries"])

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT session_id, mtime_ms FROM sdk_sessions
                WHERE project_key = $1 AND subpath = ''
                """,
                project_key,
            )
        finally:
            await conn.close()
        return [{"session_id": row["session_id"], "mtime": row["mtime_ms"]} for row in rows]

    async def delete(self, key: SessionKey) -> None:
        conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
        try:
            if key.get("subpath"):
                await conn.execute(
                    "DELETE FROM sdk_sessions WHERE project_key = $1 AND session_id = $2 AND subpath = $3",
                    key["project_key"],
                    key["session_id"],
                    key["subpath"],
                )
            else:
                # 主 transcript（无 subpath）删除时级联删掉该 session 下所有子代理 transcript
                await conn.execute(
                    "DELETE FROM sdk_sessions WHERE project_key = $1 AND session_id = $2",
                    key["project_key"],
                    key["session_id"],
                )
        finally:
            await conn.close()

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        conn = await asyncpg.connect(dsn=get_settings().postgres_dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT subpath FROM sdk_sessions
                WHERE project_key = $1 AND session_id = $2 AND subpath != ''
                """,
                key["project_key"],
                key["session_id"],
            )
        finally:
            await conn.close()
        return [row["subpath"] for row in rows]


def _merge_entries(
    existing: list[SessionStoreEntry], new_entries: list[SessionStoreEntry]
) -> list[SessionStoreEntry]:
    """带 `uuid` 的条目按 idempotency key 去重 upsert；没有 `uuid` 的条目直接追加，不做去重。"""
    merged = list(existing)
    seen_uuids = {entry["uuid"] for entry in existing if entry.get("uuid")}
    for entry in new_entries:
        entry_uuid = entry.get("uuid")
        if entry_uuid and entry_uuid in seen_uuids:
            continue
        merged.append(entry)
        if entry_uuid:
            seen_uuids.add(entry_uuid)
    return merged
