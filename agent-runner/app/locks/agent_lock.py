"""基于 Redis 的 Agent 级互斥锁（T4.2），保证同一 Agent 同一时间只有一个活跃对话执行。

粒度是 Agent 级（不是 Conversation 级）：key 用 `agent_lock:{agent_id}`。持锁期间需要覆盖一次完整的
对话执行（T4.3 SDK 调用 + T4.4 异常退出兜底保存），单次执行可能持续较久，所以不能简单地"获取时设一个
长 TTL"完事——那样正常执行时间不可预知，TTL 设太短会在执行途中过期被别人抢走，设太长又会在进程真的
崩溃时让锁悬挂太久。做法是短 TTL（默认 60s）+ 持锁期间后台协程每隔 renew_interval（默认 20s）续期一次：
- 正常路径：执行多久就续期多久，执行结束后主动释放
- 异常崩溃路径（进程被 kill、机器断电）：续期协程随进程一起消失，锁在最后一次续期后最多 ttl 秒内自动过期，
  不会永久卡死该 Agent

释放/续期都用 Lua 脚本做"校验 token 匹配后再操作"的原子操作（而不是先 GET 再 DEL/PEXPIRE 两步），
避免 A 持有的锁已经过期、B 已经拿到新锁之后，A 才姗姗来迟地把 B 的锁误删/误续期。
"""

from __future__ import annotations

import asyncio
import uuid

import redis.asyncio as aioredis

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
else
    return 0
end
"""


class AgentBusyError(Exception):
    """获取 Agent 锁失败：该 Agent 当前有另一次对话执行正在进行。调用方应据此给出明确的"Agent 正忙"反馈，
    而不是把这当成未知错误处理。"""

    def __init__(self, agent_id: uuid.UUID):
        self.agent_id = agent_id
        super().__init__(f"agent {agent_id} is busy")


def _lock_key(agent_id: uuid.UUID) -> str:
    return f"agent_lock:{agent_id}"


class AgentLock:
    """Agent 级互斥锁，用作异步上下文管理器：

        async with AgentLock(agent_id) as lock:
            ...  # 一次完整的对话执行

    获取失败时 `__aenter__` 抛 `AgentBusyError`（不会阻塞排队等待）。持锁期间自动后台续期，
    退出时（正常或异常）都会取消续期并尝试释放锁。
    """

    def __init__(
        self,
        agent_id: uuid.UUID,
        *,
        ttl_seconds: int | None = None,
        renew_interval_seconds: int | None = None,
        redis_client: aioredis.Redis | None = None,
    ):
        settings = get_settings()
        self._agent_id = agent_id
        self._key = _lock_key(agent_id)
        self._token = uuid.uuid4().hex
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.agent_lock_ttl_seconds
        self._renew_interval_seconds = (
            renew_interval_seconds
            if renew_interval_seconds is not None
            else settings.agent_lock_renew_interval_seconds
        )
        self._owns_client = redis_client is None
        self._redis = redis_client or aioredis.from_url(settings.agent_lock_redis_url)
        self._renew_task: asyncio.Task | None = None

    async def acquire(self) -> bool:
        acquired = await self._redis.set(
            self._key, self._token, nx=True, px=self._ttl_seconds * 1000
        )
        return bool(acquired)

    async def release(self) -> None:
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)

    async def _renew_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._renew_interval_seconds)
                renewed = await self._redis.eval(
                    _RENEW_SCRIPT, 1, self._key, self._token, str(self._ttl_seconds * 1000)
                )
                if not renewed:
                    logger.warning("agent_lock_renew_lost", agent_id=str(self._agent_id))
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("agent_lock_renew_failed", agent_id=str(self._agent_id))

    def begin_renewal(self) -> None:
        """启动后台续期协程。供调用方在 `acquire()` 成功后手动接管生命周期时使用（比如 T4.3 流式执行接口：
        锁需要在拿到 HTTP 409 之前就确定获取成败，但续期/释放要跟着整个流式响应的生命周期走，
        不能简单套一层 `async with`）。`__aenter__` 内部也是调这个方法，行为完全一致。"""

        if self._renew_task is None:
            self._renew_task = asyncio.create_task(self._renew_loop())

    async def end_renewal(self) -> None:
        if self._renew_task is not None:
            self._renew_task.cancel()
            try:
                await self._renew_task
            except asyncio.CancelledError:
                pass
            self._renew_task = None

    async def close(self) -> None:
        if self._owns_client:
            await self._redis.aclose()

    async def __aenter__(self) -> "AgentLock":
        if not await self.acquire():
            await self.close()
            raise AgentBusyError(self._agent_id)
        self.begin_renewal()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.end_renewal()
        try:
            await self.release()
        finally:
            await self.close()
