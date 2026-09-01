from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    session_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SendMessageRequest(BaseModel):
    prompt: str = Field(min_length=1)
