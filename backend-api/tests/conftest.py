import pytest

from app.redis_client import close_redis_client


@pytest.fixture(autouse=True)
async def _reset_redis_client_per_test():
    """redis 客户端是进程内单例，但 pytest-asyncio 默认每个测试函数一个新 event loop，
    连接池绑定着创建时的 loop，跨测试复用会报 'Event loop is closed'。每个测试后关闭并清空单例，
    下个测试首次使用时在自己的 loop 里重新建连接——只是测试隔离问题，生产环境单进程单 loop 不受影响。"""
    yield
    await close_redis_client()
