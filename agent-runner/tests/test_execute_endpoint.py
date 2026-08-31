import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from fastapi.testclient import TestClient

from app.execution import context as context_module
from app.execution import output_sync, sdk_options, workspace_cache
from app.locks.agent_lock import AgentLock
from app.server import execute as execute_module
from app.server.main import app


def _context(agent_id: uuid.UUID) -> context_module.ExecutionContext:
    return context_module.ExecutionContext(
        agent_id=agent_id,
        workspace_id="ws-" + agent_id.hex,
        permission_mode="default",
        repo_snapshot_object_key="ws/repo-v1.zip",
        repo_snapshot_version=1,
        output_snapshot_object_key="ws/output-v1.zip",
        output_snapshot_version=1,
    )


async def _fake_query(*, prompt, options):
    yield AssistantMessage(content=[TextBlock(text="hi")], model="claude", parent_tool_use_id=None)
    yield ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="sess-123",
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def prepared(tmp_path):
    cwd = tmp_path / "output"
    cwd.mkdir()
    return workspace_cache.PreparedWorkspace(cwd=cwd, add_dirs=[], skill_dirs=[])


@pytest.fixture(autouse=True)
async def _clean_lock():
    agent_ids: list[uuid.UUID] = []
    yield agent_ids
    for agent_id in agent_ids:
        lock = AgentLock(agent_id)
        await lock.release()
        await lock.close()


def test_execute_streams_sdk_messages_and_syncs_output(monkeypatch, client, prepared, _clean_lock):
    agent_id = uuid.uuid4()
    _clean_lock.append(agent_id)
    ctx = _context(agent_id)

    monkeypatch.setattr(context_module, "load_execution_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(workspace_cache, "prepare_workspace", AsyncMock(return_value=prepared))
    monkeypatch.setattr(sdk_options, "build_options", lambda *a, **k: object())
    monkeypatch.setattr(execute_module, "query", _fake_query)
    sync_mock = AsyncMock()
    monkeypatch.setattr(output_sync, "sync_output_snapshot", sync_mock)

    with client.stream(
        "POST", f"/agents/{agent_id}/execute", json={"prompt": "hello"}
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert '"type": "AssistantMessage"' in body
    assert '"type": "ResultMessage"' in body
    assert '"session_id": "sess-123"' in body
    sync_mock.assert_awaited_once_with(ctx, prepared.cwd)


def test_execute_returns_409_when_agent_not_ready(monkeypatch, client):
    agent_id = uuid.uuid4()
    monkeypatch.setattr(
        context_module,
        "load_execution_context",
        AsyncMock(side_effect=context_module.AgentNotReadyError(agent_id, "尚未就绪")),
    )

    response = client.post(f"/agents/{agent_id}/execute", json={"prompt": "hello"})

    assert response.status_code == 409
    assert "尚未就绪" in response.json()["detail"]


def test_execute_returns_409_when_agent_busy(monkeypatch, client, prepared, _clean_lock):
    agent_id = uuid.uuid4()
    _clean_lock.append(agent_id)
    ctx = _context(agent_id)
    monkeypatch.setattr(context_module, "load_execution_context", AsyncMock(return_value=ctx))

    holder = AgentLock(agent_id)

    async def _run():
        assert await holder.acquire() is True
        response = client.post(f"/agents/{agent_id}/execute", json={"prompt": "hello"})
        assert response.status_code == 409
        assert "正忙" in response.json()["detail"]

    import asyncio

    asyncio.run(_run())


def test_execute_releases_lock_and_syncs_output_even_when_sdk_raises(
    monkeypatch, client, prepared, _clean_lock
):
    agent_id = uuid.uuid4()
    _clean_lock.append(agent_id)
    ctx = _context(agent_id)

    async def _failing_query(*, prompt, options):
        yield AssistantMessage(content=[TextBlock(text="hi")], model="claude", parent_tool_use_id=None)
        raise RuntimeError("boom")

    monkeypatch.setattr(context_module, "load_execution_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(workspace_cache, "prepare_workspace", AsyncMock(return_value=prepared))
    monkeypatch.setattr(sdk_options, "build_options", lambda *a, **k: object())
    monkeypatch.setattr(execute_module, "query", _failing_query)
    sync_mock = AsyncMock()
    monkeypatch.setattr(output_sync, "sync_output_snapshot", sync_mock)

    with client.stream(
        "POST", f"/agents/{agent_id}/execute", json={"prompt": "hello"}
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert '"type": "ExecutionError"' in body
    sync_mock.assert_awaited_once()

    # 锁应该已经释放：马上再拿一次应该能成功
    async def _try_acquire():
        lock = AgentLock(agent_id)
        acquired = await lock.acquire()
        await lock.release()
        await lock.close()
        return acquired

    import asyncio

    assert asyncio.run(_try_acquire()) is True
