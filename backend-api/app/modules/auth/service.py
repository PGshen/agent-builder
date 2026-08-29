import secrets

from app.config import get_settings
from app.redis_client import get_redis_client

_TOKEN_KEY_PREFIX = "auth:token:"


def authenticate(username: str, password: str) -> bool:
    """极简单账号体系：与 .env 里的管理员账号密码常量时间比较，不做多用户查库。"""
    settings = get_settings()
    return secrets.compare_digest(username, settings.admin_username) and secrets.compare_digest(
        password, settings.admin_password
    )


async def create_token(username: str) -> tuple[str, int]:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    client = get_redis_client()
    await client.set(f"{_TOKEN_KEY_PREFIX}{token}", username, ex=settings.auth_token_ttl_seconds)
    return token, settings.auth_token_ttl_seconds


async def get_username_for_token(token: str) -> str | None:
    client = get_redis_client()
    return await client.get(f"{_TOKEN_KEY_PREFIX}{token}")


async def revoke_token(token: str) -> None:
    client = get_redis_client()
    await client.delete(f"{_TOKEN_KEY_PREFIX}{token}")
