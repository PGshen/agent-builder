from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class MCPServerConfig(Base, UUIDPKMixin, TimestampMixin):
    """MCP Server 配置，字段对齐 Claude Agent SDK `mcpServers` 选项所需结构。

    敏感字段（鉴权密钥等）是否加密存储、如何脱敏展示，由 T1.4 落地时决定；
    本任务只落 schema，`config` 先整体存成 JSONB。
    """

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
