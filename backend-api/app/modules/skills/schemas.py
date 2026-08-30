from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SkillVersionEntry(BaseModel):
    version: int
    object_key: str
    created_at: datetime


class SkillListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: int
    active_version: int
    status: str
    updated_at: datetime


class SkillDetail(SkillListItem):
    files: dict[str, str]
    versions: list[SkillVersionEntry]


class SkillUpdateRequest(BaseModel):
    files: dict[str, str]
