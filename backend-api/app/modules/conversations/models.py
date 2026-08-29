import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class Conversation(Base, UUIDPKMixin, TimestampMixin):
    """`conversation_id ↔ (agent_id, session_id)` 映射（TECH_DESIGN 4.4）。

    `session_id` 在新对话首次执行成功前为空（T4.5 决策：首次执行成功后才回写 session_id）。
    """

    __tablename__ = "conversations"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
