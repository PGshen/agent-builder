"""ORM 基础设施：所有模块的 SQLAlchemy 模型共用同一个 `Base` 和公共 mixin。

各模块的 `models.py`（`app/modules/<name>/models.py`）从这里导入 `Base`/`TimestampMixin`
定义各自的表；Alembic `env.py` 汇总导入所有模块的 `models.py` 以获得完整的 `Base.metadata`。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPKMixin:
    """UUID 主键，由 Postgres 端 `gen_random_uuid()` 生成（PG16 内置，无需 pgcrypto 扩展）。"""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
