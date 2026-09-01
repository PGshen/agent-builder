import asyncio
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from app.execution import context as context_module
from app.execution import registry
from app.locks.agent_lock import AgentLock
from app.server import main as main_module


def _context() -> context_module.ExecutionContext:
    agent_id = uuid.uuid4()
    return context_module.ExecutionContext(
        agent_id=agent_id,
        workspace_id="ws-" + agent_id.hex,
        permission_mode="default",
        repo_snapshot_object_key="ws/repo-v1.zip",
        repo_snapshot_version=1,
        output_snapshot_object_key="ws/output-v1.zip",
        output_snapshot_version=1,
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for entry in registry.snapshot():
        registry.unregister(entry)


def test_emergency_shutdown_finalizes_all_active_executions_and_exits(monkeypatch):
    ctx1, ctx2 = _context(), _context()
    lock1, lock2 = AgentLock(ctx1.agent_id), AgentLock(ctx2.agent_id)

    finalize1 = AsyncMock()
    finalize2 = AsyncMock()

    async def _run():
        entry1 = registry.register(ctx1, lock1)
        entry1.finalize = finalize1
        entry2 = registry.register(ctx2, lock2)
        entry2.finalize = finalize2

        exit_mock = Mock()
        monkeypatch.setattr(main_module.os, "_exit", exit_mock)

        await main_module._emergency_shutdown()

        finalize1.assert_awaited_once_with(update_source="emergency_fallback")
        finalize2.assert_awaited_once_with(update_source="emergency_fallback")
        exit_mock.assert_called_once_with(0)

    asyncio.run(_run())
