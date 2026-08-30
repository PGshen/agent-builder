from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class MCPServerConfig(Base, UUIDPKMixin, TimestampMixin):
    """MCP Server 配置，字段对齐 Claude Agent SDK `mcpServers` 选项所需结构。

    `config_encrypted` 是整份配置（含 stdio 的 env / sse-http 的 headers 等敏感字段）
    用 Fernet 对称加密后的密文（见 `app/modules/mcp/crypto.py`），不是明文 JSONB——
    T1.4 落地时决定：敏感字段不单独拆列，而是整体加密存储，API 层再对 env/headers 的
    值做脱敏展示（key 可见、value 打码），细节见 docs/TASKS.md T1.4 决策记录。
    """

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
