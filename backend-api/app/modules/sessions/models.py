import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin


class SDKSession(Base, TimestampMixin):
    """Claude Agent SDK SessionStore 接口落 Postgres 的记录表。

    `session_id` 由 SDK 生成/管理，不是本项目内部 UUID 主键；`data` 先存成不透明 JSONB，
    具体读写方式由 T4.1 严格按 SDK 的 SessionStore 接口实现的 adapter 决定，本任务只落 schema。
    """

    __tablename__ = "sdk_sessions"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
