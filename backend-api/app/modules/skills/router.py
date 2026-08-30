from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db_session
from app.modules.skills import service
from app.modules.skills.schemas import SkillDetail, SkillListItem, SkillUpdateRequest
from app.modules.skills.storage import SkillValidationError

router = APIRouter(prefix="/skills", tags=["skills"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[SkillListItem])
async def list_skills(db: AsyncSession = Depends(get_db_session)) -> list[SkillListItem]:
    skills = await service.list_skills(db)
    return [SkillListItem.model_validate(skill) for skill in skills]


@router.post("", response_model=SkillListItem, status_code=status.HTTP_201_CREATED)
async def create_skill(
    name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
) -> SkillListItem:
    if not name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="name 不能为空")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="仅支持上传 zip 文件")

    data = await file.read()
    try:
        skill = await service.create_skill(db, name=name.strip(), zip_bytes=data)
    except SkillValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except service.SkillNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SkillListItem.model_validate(skill)


@router.get("/{skill_id}", response_model=SkillDetail)
async def get_skill(skill_id: UUID, db: AsyncSession = Depends(get_db_session)) -> SkillDetail:
    try:
        skill, files = await service.get_skill_detail(db, skill_id)
    except service.SkillNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
    return SkillDetail(
        id=skill.id,
        name=skill.name,
        version=skill.version,
        active_version=skill.active_version,
        status=skill.status,
        updated_at=skill.updated_at,
        files=files,
        versions=skill.versions,
    )


@router.put("/{skill_id}", response_model=SkillListItem)
async def update_skill(
    skill_id: UUID,
    body: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SkillListItem:
    try:
        skill = await service.update_skill(db, skill_id, files=body.files)
    except service.SkillNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
    except SkillValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SkillListItem.model_validate(skill)


@router.post("/{skill_id}/versions/{version}/activate", response_model=SkillListItem)
async def activate_skill_version(
    skill_id: UUID,
    version: int,
    db: AsyncSession = Depends(get_db_session),
) -> SkillListItem:
    try:
        skill = await service.activate_version(db, skill_id, version=version)
    except service.SkillNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
    except service.SkillVersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SkillListItem.model_validate(skill)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, db: AsyncSession = Depends(get_db_session)) -> None:
    try:
        await service.delete_skill(db, skill_id)
    except service.SkillNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
