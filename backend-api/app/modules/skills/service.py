import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.skills import storage
from app.modules.skills.models import Skill


class SkillNotFoundError(Exception):
    pass


class SkillNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Skill 名称已存在：{name}")


class SkillVersionNotFoundError(Exception):
    def __init__(self, version: int) -> None:
        self.version = version
        super().__init__(f"版本不存在：v{version}")


def _version_entry(version: int, object_key: str) -> dict:
    return {
        "version": version,
        "object_key": object_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def list_skills(db: AsyncSession) -> list[Skill]:
    result = await db.execute(select(Skill).order_by(Skill.name))
    return list(result.scalars())


async def _get_skill_or_raise(db: AsyncSession, skill_id: uuid.UUID) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise SkillNotFoundError(str(skill_id))
    return skill


async def create_skill(db: AsyncSession, *, name: str, zip_bytes: bytes) -> Skill:
    files = storage.unpack_zip(zip_bytes)
    storage.validate_files(files)

    skill = Skill(name=name, object_key="", version=1, active_version=1, versions=[], status="active")
    db.add(skill)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise SkillNameConflictError(name) from exc

    try:
        object_key = await storage.put_skill_zip(skill.id, 1, zip_bytes)
    except Exception:
        await db.rollback()
        raise

    skill.object_key = object_key
    skill.versions = [_version_entry(1, object_key)]
    await db.commit()
    await db.refresh(skill)
    return skill


async def get_skill_detail(db: AsyncSession, skill_id: uuid.UUID) -> tuple[Skill, dict[str, str]]:
    skill = await _get_skill_or_raise(db, skill_id)
    zip_bytes = await storage.get_skill_zip(skill.object_key)
    files = storage.unpack_zip(zip_bytes)
    return skill, files


async def update_skill(db: AsyncSession, skill_id: uuid.UUID, *, files: dict[str, str]) -> Skill:
    """保存即新增一个版本（不覆盖旧对象），新版本自动成为当前激活版本。"""
    storage.validate_files(files)
    skill = await _get_skill_or_raise(db, skill_id)

    new_version = skill.version + 1
    zip_bytes = storage.pack_zip(files)
    object_key = await storage.put_skill_zip(skill.id, new_version, zip_bytes)

    skill.object_key = object_key
    skill.version = new_version
    skill.active_version = new_version
    skill.versions = [*skill.versions, _version_entry(new_version, object_key)]
    await db.commit()
    await db.refresh(skill)
    return skill


async def activate_version(db: AsyncSession, skill_id: uuid.UUID, *, version: int) -> Skill:
    """把某个历史版本重新设为当前激活版本（回滚），不改动/删除任何版本记录。"""
    skill = await _get_skill_or_raise(db, skill_id)
    entry = next((v for v in skill.versions if v["version"] == version), None)
    if entry is None:
        raise SkillVersionNotFoundError(version)

    skill.active_version = version
    skill.object_key = entry["object_key"]
    await db.commit()
    await db.refresh(skill)
    return skill


async def delete_skill(db: AsyncSession, skill_id: uuid.UUID) -> None:
    skill = await _get_skill_or_raise(db, skill_id)
    for entry in skill.versions:
        await storage.delete_skill_zip(entry["object_key"])
    await db.delete(skill)
    await db.commit()
