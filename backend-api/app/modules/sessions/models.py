import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin


class SDKSession(Base, TimestampMixin):
    """Claude Agent SDK SessionStore 接口落 Postgres 的记录表。

    主键是 SDK `SessionKey` 的三元组（`project_key` + `session_id` + `subpath`），不是单纯的
    `session_id`——SDK 用 `subpath`（如 `subagents/agent-{id}`）区分主会话与子代理的独立
    transcript，同一 `session_id` 下会有多行记录。`agent_id` 由 Runner 侧的 adapter 在写入时
    附带（与 `project_key` 的取值无关，只用于 FK 级联删除，Agent 删除时对应 session 记录一并清理）。
    `entries` 是 SDK transcript 条目的不透明追加数组（JSONL 逐行对象的 JSON 表示），adapter 只做
    透传，不解析内容；`mtime_ms` 记录最近一次写入时间（Unix 毫秒），供 `list_sessions` 按新旧排序。
    """

    __tablename__ = "sdk_sessions"

    project_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subpath: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entries: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    mtime_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
