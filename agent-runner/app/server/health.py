import asyncio
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Response, status
from minio import Minio

from app.cache import check_local_cache_writable
from app.config import get_settings
from app.logging_config import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


async def _check_postgres() -> bool:
    settings = get_settings()
    try:
        conn = await asyncpg.connect(dsn=settings.postgres_dsn, timeout=3)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return True
    except Exception:
        logger.exception("postgres_health_check_failed")
        return False


async def _check_redis() -> bool:
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
    try:
        return bool(await client.ping())
    except Exception:
        logger.exception("redis_health_check_failed")
        return False
    finally:
        await client.aclose()


def _check_minio_sync() -> bool:
    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=False,
    )
    return client.bucket_exists(settings.minio_bucket_workspaces)


async def _check_minio() -> bool:
    try:
        return await asyncio.to_thread(_check_minio_sync)
    except Exception:
        logger.exception("minio_health_check_failed")
        return False


@router.get("/health")
async def health(response: Response) -> dict:
    """进程存活：只要能返回这个响应就说明进程活着；readiness：各依赖连通性分别体现在 dependencies 里。"""

    postgres_ok, redis_ok, minio_ok = await asyncio.gather(
        _check_postgres(), _check_redis(), _check_minio()
    )
    cache_writable = check_local_cache_writable()

    all_ok = postgres_ok and redis_ok and minio_ok and cache_writable
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if all_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "postgres": {"connected": postgres_ok},
            "redis": {"connected": redis_ok},
            "minio": {"connected": minio_ok},
            "local_cache": {"writable": cache_writable},
        },
    }
