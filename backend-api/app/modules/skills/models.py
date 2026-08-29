from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class Skill(Base, UUIDPKMixin, TimestampMixin):
    """一个 Skill 对应 MinIO 里一个 zip 对象，本表只存元数据（T1.2 落地存取逻辑）。"""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # MinIO 对象 key（bucket 固定为 settings.minio_bucket_skills）
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 每次保存递增，供 Agent 绑定关系判断"有更新"用（v1 只做元数据记录，不做自动推送）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
