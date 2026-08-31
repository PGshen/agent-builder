import json
import uuid

import pytest

from app.sessions import store as store_module
from app.sessions.store import PostgresSessionStore


class _FakeRow(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeConnection:
    """内存假 asyncpg 连接：只认识 store.py 用到的几种查询形状，够单测用。"""

    def __init__(self, table: dict):
        self._table = table

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query: str, *args):
        if "FOR UPDATE" in query or (query.strip().startswith("SELECT entries") and "subpath = $3" in query):
            key = args
            row = self._table.get(key)
            if row is None:
                return None
            return _FakeRow(entries=json.dumps(row["entries"]))
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def execute(self, query: str, *args):
        if query.strip().startswith("INSERT INTO sdk_sessions"):
            project_key, session_id, subpath, agent_id, entries_json, mtime_ms = args
            self._table[(project_key, session_id, subpath)] = {
                "agent_id": agent_id,
                "entries": json.loads(entries_json),
                "mtime_ms": mtime_ms,
            }
        elif query.strip().startswith("DELETE FROM sdk_sessions"):
            if len(args) == 3:
                self._table.pop(args, None)
            else:
                project_key, session_id = args
                for key in [k for k in self._table if k[0] == project_key and k[1] == session_id]:
                    self._table.pop(key)
        else:
            raise AssertionError(f"unexpected execute query: {query}")

    async def fetch(self, query: str, *args):
        if "session_id, mtime_ms" in query:
            (project_key,) = args
            return [
                _FakeRow(session_id=key[1], mtime_ms=row["mtime_ms"])
                for key, row in self._table.items()
                if key[0] == project_key and key[2] == ""
            ]
        if "SELECT subpath" in query:
            project_key, session_id = args
            return [
                _FakeRow(subpath=key[2])
                for key in self._table
                if key[0] == project_key and key[1] == session_id and key[2] != ""
            ]
        raise AssertionError(f"unexpected fetch query: {query}")

    async def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    table: dict = {}

    async def _connect(dsn):
        return FakeConnection(table)

    monkeypatch.setattr(store_module.asyncpg, "connect", _connect)
    return table


async def test_load_returns_none_for_unknown_key(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    result = await adapter.load({"project_key": "proj", "session_id": "sess-1"})
    assert result is None


async def test_append_then_load_round_trips_entries(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    key = {"project_key": "proj", "session_id": "sess-1"}
    entries = [
        {"type": "user", "uuid": "e1", "timestamp": "t1"},
        {"type": "assistant", "uuid": "e2", "timestamp": "t2"},
    ]

    await adapter.append(key, entries)
    loaded = await adapter.load(key)

    assert loaded == entries


async def test_append_dedups_entries_by_uuid_idempotency_key(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    key = {"project_key": "proj", "session_id": "sess-1"}

    await adapter.append(key, [{"type": "user", "uuid": "e1", "timestamp": "t1"}])
    await adapter.append(key, [{"type": "user", "uuid": "e1", "timestamp": "t1"}, {"type": "assistant", "uuid": "e2", "timestamp": "t2"}])

    loaded = await adapter.load(key)
    assert loaded == [
        {"type": "user", "uuid": "e1", "timestamp": "t1"},
        {"type": "assistant", "uuid": "e2", "timestamp": "t2"},
    ]


async def test_append_without_uuid_never_dedups(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    key = {"project_key": "proj", "session_id": "sess-1"}
    entry = {"type": "mode-marker", "timestamp": "t1"}

    await adapter.append(key, [entry])
    await adapter.append(key, [entry])

    loaded = await adapter.load(key)
    assert loaded == [entry, entry]


async def test_subpath_keeps_main_and_subagent_transcripts_independent(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    main_key = {"project_key": "proj", "session_id": "sess-1"}
    sub_key = {"project_key": "proj", "session_id": "sess-1", "subpath": "subagents/agent-a"}

    await adapter.append(main_key, [{"type": "user", "uuid": "m1", "timestamp": "t1"}])
    await adapter.append(sub_key, [{"type": "tool_use", "uuid": "s1", "timestamp": "t1"}])

    assert await adapter.load(main_key) == [{"type": "user", "uuid": "m1", "timestamp": "t1"}]
    assert await adapter.load(sub_key) == [{"type": "tool_use", "uuid": "s1", "timestamp": "t1"}]
    assert await adapter.list_subkeys({"project_key": "proj", "session_id": "sess-1"}) == ["subagents/agent-a"]


async def test_list_sessions_excludes_subpath_entries(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    await adapter.append({"project_key": "proj", "session_id": "sess-1"}, [{"type": "user", "uuid": "m1", "timestamp": "t1"}])
    await adapter.append(
        {"project_key": "proj", "session_id": "sess-1", "subpath": "subagents/agent-a"},
        [{"type": "tool_use", "uuid": "s1", "timestamp": "t1"}],
    )
    await adapter.append({"project_key": "other-proj", "session_id": "sess-2"}, [{"type": "user", "uuid": "m2", "timestamp": "t2"}])

    listed = await adapter.list_sessions("proj")

    assert [entry["session_id"] for entry in listed] == ["sess-1"]


async def test_delete_main_key_cascades_to_subagent_transcripts(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    main_key = {"project_key": "proj", "session_id": "sess-1"}
    sub_key = {"project_key": "proj", "session_id": "sess-1", "subpath": "subagents/agent-a"}
    await adapter.append(main_key, [{"type": "user", "uuid": "m1", "timestamp": "t1"}])
    await adapter.append(sub_key, [{"type": "tool_use", "uuid": "s1", "timestamp": "t1"}])

    await adapter.delete(main_key)

    assert await adapter.load(main_key) is None
    assert await adapter.load(sub_key) is None


async def test_delete_with_subpath_only_removes_that_entry(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    main_key = {"project_key": "proj", "session_id": "sess-1"}
    sub_key = {"project_key": "proj", "session_id": "sess-1", "subpath": "subagents/agent-a"}
    await adapter.append(main_key, [{"type": "user", "uuid": "m1", "timestamp": "t1"}])
    await adapter.append(sub_key, [{"type": "tool_use", "uuid": "s1", "timestamp": "t1"}])

    await adapter.delete(sub_key)

    assert await adapter.load(main_key) is not None
    assert await adapter.load(sub_key) is None


async def test_append_with_no_entries_is_a_noop(fake_db):
    adapter = PostgresSessionStore(agent_id=uuid.uuid4())
    key = {"project_key": "proj", "session_id": "sess-1"}

    await adapter.append(key, [])

    assert await adapter.load(key) is None
