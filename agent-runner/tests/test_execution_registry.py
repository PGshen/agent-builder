import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from app.execution import context as context_module
from app.execution import output_sync, registry
from app.locks.agent_lock import AgentLock


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


def test_finalize_syncs_output_and_releases_lock(tmp_path, monkeypatch):
    ctx = _context()
    lock = AgentLock(ctx.agent_id)
    sync_mock = AsyncMock()
    monkeypatch.setattr(output_sync, "sync_output_snapshot", sync_mock)

    async def _run():
        assert await lock.acquire() is True
        entry = registry.register(ctx, lock)
        entry.cwd = tmp_path
        await entry.finalize()

        # 锁已释放：马上再拿一次应该成功
        other = AgentLock(ctx.agent_id)
        acquired = await other.acquire()
        await other.release()
        await other.close()
        return acquired

    assert asyncio.run(_run()) is True
    sync_mock.assert_awaited_once_with(ctx, tmp_path)


def test_finalize_is_idempotent_and_uses_emergency_source_once(tmp_path, monkeypatch):
    ctx = _context()
    lock = AgentLock(ctx.agent_id)
    sync_mock = AsyncMock()
    monkeypatch.setattr(output_sync, "sync_output_snapshot", sync_mock)

    async def _run():
        assert await lock.acquire() is True
        entry = registry.register(ctx, lock)
        entry.cwd = tmp_path

        # 模拟正常路径与 SIGTERM 兜底路径并发触发同一条记录的 finalize
        await asyncio.gather(
            entry.finalize(),
            entry.finalize(update_source=output_sync.SOURCE_EMERGENCY_FALLBACK),
        )

    asyncio.run(_run())

    sync_mock.assert_awaited_once()


def test_registry_register_and_unregister_roundtrip():
    ctx = _context()
    lock = AgentLock(ctx.agent_id)

    entry = registry.register(ctx, lock)
    assert entry in registry.snapshot()

    registry.unregister(entry)
    assert entry not in registry.snapshot()


def test_finalize_without_cwd_still_releases_lock():
    ctx = _context()
    lock = AgentLock(ctx.agent_id)

    async def _run():
        assert await lock.acquire() is True
        entry = registry.register(ctx, lock)
        # cwd 为 None：模拟 SIGTERM 在 workspace 准备完成前就到达
        await entry.finalize()

        other = AgentLock(ctx.agent_id)
        acquired = await other.acquire()
        await other.release()
        await other.close()
        return acquired

    assert asyncio.run(_run()) is True
