import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp import crypto
from app.modules.mcp.masking import merge_secret_fields
from app.modules.mcp.models import MCPServerConfig


class MCPServerNotFoundError(Exception):
    pass


class MCPServerNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"MCP Server 名称已存在：{name}")


async def list_mcp_servers(db: AsyncSession) -> list[MCPServerConfig]:
    result = await db.execute(select(MCPServerConfig).order_by(MCPServerConfig.name))
    return list(result.scalars())


async def _get_mcp_server_or_raise(db: AsyncSession, mcp_id: uuid.UUID) -> MCPServerConfig:
    mcp_server = await db.get(MCPServerConfig, mcp_id)
    if mcp_server is None:
        raise MCPServerNotFoundError(str(mcp_id))
    return mcp_server


async def create_mcp_server(db: AsyncSession, *, name: str, config: dict) -> MCPServerConfig:
    mcp_server = MCPServerConfig(name=name, config_encrypted=crypto.encrypt_config(config), status="active")
    db.add(mcp_server)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise MCPServerNameConflictError(name) from exc
    await db.refresh(mcp_server)
    return mcp_server


async def get_mcp_server_detail(db: AsyncSession, mcp_id: uuid.UUID) -> tuple[MCPServerConfig, dict]:
    mcp_server = await _get_mcp_server_or_raise(db, mcp_id)
    config = crypto.decrypt_config(mcp_server.config_encrypted)
    return mcp_server, config


async def update_mcp_server(
    db: AsyncSession, mcp_id: uuid.UUID, *, name: str, config: dict, status: str
) -> tuple[MCPServerConfig, dict]:
    mcp_server = await _get_mcp_server_or_raise(db, mcp_id)
    old_config = crypto.decrypt_config(mcp_server.config_encrypted)
    merged_config = merge_secret_fields(old_config, config)

    mcp_server.name = name
    mcp_server.config_encrypted = crypto.encrypt_config(merged_config)
    mcp_server.status = status
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise MCPServerNameConflictError(name) from exc
    await db.refresh(mcp_server)
    return mcp_server, merged_config


async def delete_mcp_server(db: AsyncSession, mcp_id: uuid.UUID) -> None:
    mcp_server = await _get_mcp_server_or_raise(db, mcp_id)
    await db.delete(mcp_server)
    await db.commit()
