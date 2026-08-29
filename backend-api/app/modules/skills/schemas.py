from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SkillListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: int
    status: str
    updated_at: datetime


class SkillDetail(SkillListItem):
    files: dict[str, str]


class SkillUpdateRequest(BaseModel):
    files: dict[str, str]
