import time

from app import dispatch_lock


class _FakeRedis:
    """最小的内存假实现，只覆盖 `set(nx=True, ex=...)` 语义，避免测试依赖真实 Redis。"""

    def __init__(self):
        self._store: dict[str, float] = {}  # key -> 过期时间戳

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        now = time.monotonic()
        expires_at = self._store.get(key)
        if nx and expires_at is not None and expires_at > now:
            return False
        self._store[key] = now + (ex or 0)
        return True


def test_first_acquire_succeeds(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(dispatch_lock, "_redis_client", lambda: fake)

    assert dispatch_lock.try_acquire_dispatch_lock("agent-1") is True


def test_second_acquire_within_ttl_fails(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(dispatch_lock, "_redis_client", lambda: fake)

    assert dispatch_lock.try_acquire_dispatch_lock("agent-1") is True
    assert dispatch_lock.try_acquire_dispatch_lock("agent-1") is False


def test_different_agents_do_not_block_each_other(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(dispatch_lock, "_redis_client", lambda: fake)

    assert dispatch_lock.try_acquire_dispatch_lock("agent-1") is True
    assert dispatch_lock.try_acquire_dispatch_lock("agent-2") is True
