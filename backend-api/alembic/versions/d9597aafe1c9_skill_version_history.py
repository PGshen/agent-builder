"""skill version history

Revision ID: d9597aafe1c9
Revises: 191e1f381995
Create Date: 2026-08-30 11:43:54.565900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd9597aafe1c9'
down_revision: Union[str, None] = '191e1f381995'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default 只是为了让已有行在加 NOT NULL 列时有值可填；数据回填后就去掉，
    # 后续插入统一由 ORM 层显式赋值（跟本项目其它表的一贯做法一致）
    op.add_column('skills', sa.Column('active_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column(
        'skills',
        sa.Column('versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
    )

    # 老数据只有一个"当前"版本（用现有 version/object_key 的值），把它补成 versions 列表里的第一条记录，
    # 且 active_version 等于现有 version——语义上等价于"这是它唯一存在过的版本，而且正在生效"
    op.execute(
        """
        UPDATE skills
        SET active_version = version,
            versions = jsonb_build_array(
                jsonb_build_object(
                    'version', version,
                    'object_key', object_key,
                    'created_at', to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
                )
            )
        """
    )

    op.alter_column('skills', 'active_version', server_default=None)
    op.alter_column('skills', 'versions', server_default=None)


def downgrade() -> None:
    op.drop_column('skills', 'versions')
    op.drop_column('skills', 'active_version')
