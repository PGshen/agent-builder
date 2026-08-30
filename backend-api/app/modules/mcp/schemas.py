from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StdioMCPServerConfig(BaseModel):
    """对应 SDK `mcpServers` 里的 stdio 类型：本地起子进程通过 stdio 通信。"""

    type: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class SSEMCPServerConfig(BaseModel):
    """对应 SDK `mcpServers` 里的 sse 类型：远程 Server-Sent Events 端点。"""

    type: Literal["sse"] = "sse"
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


class HTTPMCPServerConfig(BaseModel):
    """对应 SDK `mcpServers` 里的 http 类型：远程流式 HTTP 端点。"""

    type: Literal["http"] = "http"
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


MCPServerConfigInput = Annotated[
    Union[StdioMCPServerConfig, SSEMCPServerConfig, HTTPMCPServerConfig],
    Field(discriminator="type"),
]


class MCPServerCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    config: MCPServerConfigInput


class MCPServerUpdateRequest(BaseModel):
    name: str = Field(min_length=1)
    config: MCPServerConfigInput
    status: str = "active"


class MCPServerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    updated_at: datetime


class MCPServerDetail(MCPServerListItem):
    # 返回给前端的是脱敏后的 dict（env/headers 的 value 被打码），不是上面几个强类型 config 模型，
    # 因为打码后 value 不再是"真实的"该类型取值（比如 env 的 value 被替换成 "********"）
    config: dict
