import asyncio
import uuid

import pytest
import redis.asyncio as aioredis

from app.config import get_settings
from app.locks.agent_lock import AgentBusyError, AgentLock, _lock_key


@pytest.fixture
async def redis_client():
    client = aioredis.from_url(get_settings().agent_lock_redis_url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def agent_id():
    return uuid.uuid4()


async def test_second_concurrent_acquire_raises_agent_busy(agent_id, redis_client):
    async with AgentLock(agent_id, redis_client=redis_client):
        with pytest.raises(AgentBusyError) as exc_info:
            async with AgentLock(agent_id, redis_client=redis_client):
                pass
        assert exc_info.value.agent_id == agent_id


async def test_lock_released_on_normal_exit_allows_next_acquire(agent_id, redis_client):
    async with AgentLock(agent_id, redis_client=redis_client):
        pass

    async with AgentLock(agent_id, redis_client=redis_client):
        assert await redis_client.get(_lock_key(agent_id)) is not None


async def test_lock_released_on_exception_allows_next_acquire(agent_id, redis_client):
    with pytest.raises(RuntimeError):
        async with AgentLock(agent_id, redis_client=redis_client):
            raise RuntimeError("boom")

    acquired = await AgentLock(agent_id, redis_client=redis_client).acquire()
    assert acquired is True
    await redis_client.delete(_lock_key(agent_id))


async def test_expired_lock_from_crashed_holder_is_auto_released(agent_id, redis_client):
    # 模拟持锁进程崩溃：直接 acquire 但从不进入 renew 循环、也不释放，短 TTL 到期后应能被别人拿到
    crashed_lock = AgentLock(agent_id, ttl_seconds=1, redis_client=redis_client)
    assert await crashed_lock.acquire() is True

    # 崩溃后锁还没过期时，别的请求应该明确拿到"正忙"，而不是排队卡住
    still_held = AgentLock(agent_id, redis_client=redis_client)
    assert await still_held.acquire() is False

    await asyncio.sleep(1.2)  # 等待 TTL 到期

    async with AgentLock(agent_id, ttl_seconds=1, redis_client=redis_client):
        pass


async def test_renew_loop_extends_ttl_past_initial_ttl(agent_id, redis_client):
    lock = AgentLock(agent_id, ttl_seconds=1, renew_interval_seconds=0.3, redis_client=redis_client)
    async with lock:
        await asyncio.sleep(1.5)
        # 若续期没生效，1.5s 后 key（初始 ttl=1s）应该已经过期消失
        assert await redis_client.get(_lock_key(agent_id)) is not None
