from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base, TimestampMixin, UUIDPKMixin


class Skill(Base, UUIDPKMixin, TimestampMixin):
    """一个 Skill 在 MinIO 里对应多个 zip 对象——每次保存都新增一个版本对象，不覆盖旧的
    （T1.2 是覆盖更新，本次改成保留历史版本）。本表只存元数据。"""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # 当前激活版本对应的 MinIO 对象 key（bucket 固定为 settings.minio_bucket_skills），
    # 冗余存一份是为了读取内容时不用现解析 versions 列表，跟 active_version 保持同步更新
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 历史上创建过的最新版本号，只增不减（约等于 versions 列表长度，语义上是"总共存过几个版本"）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 当前生效/激活的版本号——正常保存时等于 version；回滚到旧版本时可以小于 version
    active_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 版本历史记录：[{"version": int, "object_key": str, "created_at": iso8601 str}, ...]，只追加不删除
    versions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
