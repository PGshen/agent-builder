"""派发去重锁：同一个 Agent 的刷新耗时可能明显长于扫描间隔，用 Redis SET NX EX 防止还没跑完就被下一轮重复派发。

不要求刷新任务（T3.2，跑在 agent-runner）主动清除这个 key——TTL 到期自动放行下一次派发即可，
scheduler 自己建立、自己靠 TTL 兜底，不产生跨服务的清理依赖。
"""

from functools import lru_cache

import redis

from app.config import get_settings

_LOCK_KEY_PREFIX = "scheduler:dispatching:"


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().scheduler_lock_redis_url)


def try_acquire_dispatch_lock(agent_id: str) -> bool:
    """成功获取（此前未被锁定）返回 True，已被其它/上一轮派发锁定则返回 False。"""

    ttl = get_settings().scheduler_dispatch_lock_ttl_seconds
    return bool(_redis_client().set(f"{_LOCK_KEY_PREFIX}{agent_id}", "1", nx=True, ex=ttl))
