"""sdk_sessions: composite SessionKey (project_key/session_id/subpath) + entries/mtime

Revision ID: 9d3b6a2c1e4f
Revises: 7c2a4e1f9b3d
Create Date: 2026-08-31 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9d3b6a2c1e4f"
down_revision = "7c2a4e1f9b3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # T4.1 才发现 SDK 的 SessionKey 是 (project_key, session_id, subpath) 三元组（subpath 用于
    # 区分子代理独立 transcript），T1.1 落地时只按 session_id 单列建的表不满足这个要求；此表在
    # T4.1 之前没有任何写入代码路径，直接 drop/recreate，不需要数据迁移。
    op.drop_index(op.f("ix_sdk_sessions_agent_id"), table_name="sdk_sessions")
    op.drop_table("sdk_sessions")

    op.create_table(
        "sdk_sessions",
        sa.Column("project_key", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("subpath", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "entries",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("mtime_ms", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_key", "session_id", "subpath"),
    )
    op.create_index(op.f("ix_sdk_sessions_agent_id"), "sdk_sessions", ["agent_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sdk_sessions_agent_id"), table_name="sdk_sessions")
    op.drop_table("sdk_sessions")

    op.create_table(
        "sdk_sessions",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(op.f("ix_sdk_sessions_agent_id"), "sdk_sessions", ["agent_id"], unique=False)
