from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db_session
from app.modules.mcp import service
from app.modules.mcp.masking import mask_config
from app.modules.mcp.schemas import (
    MCPServerCreateRequest,
    MCPServerDetail,
    MCPServerListItem,
    MCPServerUpdateRequest,
)

router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[MCPServerListItem])
async def list_mcp_servers(db: AsyncSession = Depends(get_db_session)) -> list[MCPServerListItem]:
    mcp_servers = await service.list_mcp_servers(db)
    return [MCPServerListItem.model_validate(item) for item in mcp_servers]


@router.post("", response_model=MCPServerDetail, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: MCPServerCreateRequest, db: AsyncSession = Depends(get_db_session)
) -> MCPServerDetail:
    try:
        mcp_server = await service.create_mcp_server(
            db, name=body.name.strip(), config=body.config.model_dump()
        )
    except service.MCPServerNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MCPServerDetail(
        id=mcp_server.id,
        name=mcp_server.name,
        status=mcp_server.status,
        updated_at=mcp_server.updated_at,
        config=mask_config(body.config.model_dump()),
    )


@router.get("/{mcp_id}", response_model=MCPServerDetail)
async def get_mcp_server(mcp_id: UUID, db: AsyncSession = Depends(get_db_session)) -> MCPServerDetail:
    try:
        mcp_server, config = await service.get_mcp_server_detail(db, mcp_id)
    except service.MCPServerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="MCP Server 不存在") from exc
    return MCPServerDetail(
        id=mcp_server.id,
        name=mcp_server.name,
        status=mcp_server.status,
        updated_at=mcp_server.updated_at,
        config=mask_config(config),
    )


@router.put("/{mcp_id}", response_model=MCPServerDetail)
async def update_mcp_server(
    mcp_id: UUID,
    body: MCPServerUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> MCPServerDetail:
    try:
        mcp_server, config = await service.update_mcp_server(
            db,
            mcp_id,
            name=body.name.strip(),
            config=body.config.model_dump(),
            status=body.status,
        )
    except service.MCPServerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="MCP Server 不存在") from exc
    except service.MCPServerNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return MCPServerDetail(
        id=mcp_server.id,
        name=mcp_server.name,
        status=mcp_server.status,
        updated_at=mcp_server.updated_at,
        config=mask_config(config),
    )


@router.delete("/{mcp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(mcp_id: UUID, db: AsyncSession = Depends(get_db_session)) -> None:
    try:
        await service.delete_mcp_server(db, mcp_id)
    except service.MCPServerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="MCP Server 不存在") from exc
