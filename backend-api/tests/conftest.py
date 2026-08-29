import pytest

from app.db import dispose_engine
from app.redis_client import close_redis_client


@pytest.fixture(autouse=True)
async def _reset_redis_client_per_test():
    """redis 客户端是进程内单例，但 pytest-asyncio 默认每个测试函数一个新 event loop，
    连接池绑定着创建时的 loop，跨测试复用会报 'Event loop is closed'。每个测试后关闭并清空单例，
    下个测试首次使用时在自己的 loop 里重新建连接——只是测试隔离问题，生产环境单进程单 loop 不受影响。"""
    yield
    await close_redis_client()


@pytest.fixture(autouse=True)
async def _reset_db_engine_per_test():
    """同上：SQLAlchemy async engine 也是进程内单例，连接池同样绑定创建时的 event loop，
    T1.2 起业务测试开始真正读写数据库，需要同样的每测试重置，否则第二个碰数据库的测试
    会报 'Event loop is closed'。"""
    yield
    await dispose_engine()
