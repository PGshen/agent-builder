from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentRepositoryInput(BaseModel):
    # 编辑时，已存在的仓库带上原 id 以便沿用其加密凭证（MASK_SENTINEL 占位符场景）；新增仓库不传/传 None
    id: UUID | None = None
    url: str = Field(min_length=1)
    branch: str | None = None
    auth_type: Literal["none", "token", "ssh_key"] = "none"
    # 明文（创建/真正修改凭证时）或 MASK_SENTINEL 占位符（未修改，编辑时沿用原值）；auth_type=none 时忽略
    auth_credential: str | None = None


class AgentRepositoryDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    branch: str | None
    auth_type: str
    # 永远是打码值或 None，从不返回明文
    auth_credential: str | None
    position: int
    last_synced_at: datetime | None
    last_synced_commit: str | None


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    permission_mode: str = "default"
    repo_refresh_interval_minutes: int = Field(default=30, ge=1)
    skill_ids: list[UUID] = Field(default_factory=list)
    mcp_server_ids: list[UUID] = Field(default_factory=list)
    repositories: list[AgentRepositoryInput] = Field(default_factory=list)


class AgentUpdateRequest(AgentCreateRequest):
    pass


class BoundSkill(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class BoundMCPServer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    permission_mode: str
    repo_refresh_interval_minutes: int
    updated_at: datetime
    skill_count: int
    mcp_server_count: int
    repository_count: int


class AgentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    workspace_id: str
    permission_mode: str
    repo_refresh_interval_minutes: int
    status: str
    status_message: str | None
    updated_at: datetime
    skills: list[BoundSkill]
    mcp_servers: list[BoundMCPServer]
    repositories: list[AgentRepositoryDetail]
