import uuid

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

    skill = Skill(name=name, object_key="", version=1, status="active")
    db.add(skill)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise SkillNameConflictError(name) from exc

    try:
        object_key = await storage.put_skill_zip(skill.id, zip_bytes)
    except Exception:
        await db.rollback()
        raise

    skill.object_key = object_key
    await db.commit()
    await db.refresh(skill)
    return skill


async def get_skill_detail(db: AsyncSession, skill_id: uuid.UUID) -> tuple[Skill, dict[str, str]]:
    skill = await _get_skill_or_raise(db, skill_id)
    zip_bytes = await storage.get_skill_zip(skill.object_key)
    files = storage.unpack_zip(zip_bytes)
    return skill, files


async def update_skill(db: AsyncSession, skill_id: uuid.UUID, *, files: dict[str, str]) -> Skill:
    storage.validate_files(files)
    skill = await _get_skill_or_raise(db, skill_id)

    zip_bytes = storage.pack_zip(files)
    object_key = await storage.put_skill_zip(skill.id, zip_bytes)

    skill.object_key = object_key
    skill.version += 1
    await db.commit()
    await db.refresh(skill)
    return skill


async def delete_skill(db: AsyncSession, skill_id: uuid.UUID) -> None:
    skill = await _get_skill_or_raise(db, skill_id)
    await storage.delete_skill_zip(skill.object_key)
    await db.delete(skill)
    await db.commit()
