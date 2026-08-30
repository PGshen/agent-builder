import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class Agent(Base, UUIDPKMixin, TimestampMixin):
    """Agent 元数据。绑定的 skill/MCP 用关联表（AgentSkill/AgentMCPServer），仓库列表用独立表
    （AgentRepository）——三者都是"引用独立生命周期的实体/结构化的多值列表"，不适合内嵌数组字段。
    """

    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # 该 Agent 的能力描述（用途、擅长什么），纯展示用途，不参与 SDK 调用组装
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # workspace 的唯一标识，供 MinIO 快照 object key 前缀 / Runner 本地缓存目录命名使用；
    # 独立生成（不直接复用 id），保持"内部主键"与"对外可见的 workspace 标识"解耦
    workspace_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, default=lambda: uuid.uuid4().hex
    )
    # 对齐 SDK 的 permissionMode 取值，v1 先存字符串，具体可配置粒度见 TECH_DESIGN 8 待细化项
    permission_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    repo_refresh_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # 初始化中 / 就绪 / 失败（T2.4 状态流转）
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="initializing")
    # 失败状态下的原因，供 T2.4 前端展示；成功/初始化中时为空
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentSkill(Base):
    """Agent × Skill 绑定关系（多对多关联表）。"""

    __tablename__ = "agent_skills"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class AgentMCPServer(Base):
    """Agent × MCPServerConfig 绑定关系（多对多关联表）。"""

    __tablename__ = "agent_mcp_servers"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class AgentRepository(Base, UUIDPKMixin, TimestampMixin):
    """Agent 绑定的代码仓库（一个 Agent 可绑定多个），仓库在 workspace 中只读（TECH_DESIGN 4.3）。"""

    __tablename__ = "agent_repositories"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # none / token / ssh_key 等，具体取值在 T2.1 落地时约束；凭证存储（是否加密）与 T1.4 敏感字段处理方式保持一致
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    auth_credential: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 同一 Agent 下多仓库的展示/目录命名顺序
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkspaceSnapshot(Base):
    """Workspace 两段式模型的元信息：仓库快照与输出快照独立版本化（TECH_DESIGN 4.3 / 5），
    与 Agent 一对一，用 agent_id 作为主键。"""

    __tablename__ = "workspace_snapshots"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )

    repo_snapshot_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repo_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repo_snapshot_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    output_snapshot_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_snapshot_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # conversation_sync（对话执行完成后正常同步） / emergency_fallback（异常退出兜底保存，T4.4）
    output_snapshot_update_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
