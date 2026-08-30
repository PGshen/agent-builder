from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db_session
from app.modules.agents import masking, service
from app.modules.agents.models import Agent, AgentRepository
from app.modules.agents.schemas import (
    AgentCreateRequest,
    AgentDetail,
    AgentListItem,
    AgentRepositoryDetail,
    AgentUpdateRequest,
    BoundMCPServer,
    BoundSkill,
)
from app.modules.agents.service import AgentListEntry
from app.modules.mcp.models import MCPServerConfig
from app.modules.skills.models import Skill

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(get_current_admin)])


def _to_list_item(entry: AgentListEntry) -> AgentListItem:
    return AgentListItem(
        id=entry.agent.id,
        name=entry.agent.name,
        description=entry.agent.description,
        status=entry.agent.status,
        permission_mode=entry.agent.permission_mode,
        repo_refresh_interval_minutes=entry.agent.repo_refresh_interval_minutes,
        updated_at=entry.agent.updated_at,
        skill_count=entry.skill_count,
        mcp_server_count=entry.mcp_server_count,
        repository_count=entry.repository_count,
    )


def _to_detail(
    agent: Agent, skills: list[Skill], mcp_servers: list[MCPServerConfig], repositories: list[AgentRepository]
) -> AgentDetail:
    return AgentDetail(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        workspace_id=agent.workspace_id,
        permission_mode=agent.permission_mode,
        repo_refresh_interval_minutes=agent.repo_refresh_interval_minutes,
        status=agent.status,
        status_message=agent.status_message,
        updated_at=agent.updated_at,
        skills=[BoundSkill.model_validate(skill) for skill in skills],
        mcp_servers=[BoundMCPServer.model_validate(mcp_server) for mcp_server in mcp_servers],
        repositories=[
            AgentRepositoryDetail(
                id=repo.id,
                url=repo.url,
                branch=repo.branch,
                auth_type=repo.auth_type,
                auth_credential=masking.mask_credential(repo),
                position=repo.position,
                last_synced_at=repo.last_synced_at,
                last_synced_commit=repo.last_synced_commit,
                last_sync_error=repo.last_sync_error,
            )
            for repo in repositories
        ],
    )


@router.get("", response_model=list[AgentListItem])
async def list_agents(db: AsyncSession = Depends(get_db_session)) -> list[AgentListItem]:
    entries = await service.list_agents(db)
    return [_to_list_item(entry) for entry in entries]


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentCreateRequest, db: AsyncSession = Depends(get_db_session)) -> AgentDetail:
    try:
        agent = await service.create_agent(
            db,
            name=body.name.strip(),
            description=(body.description.strip() or None) if body.description else None,
            permission_mode=body.permission_mode,
            repo_refresh_interval_minutes=body.repo_refresh_interval_minutes,
            skill_ids=body.skill_ids,
            mcp_server_ids=body.mcp_server_ids,
            repositories=body.repositories,
        )
    except service.AgentNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.InvalidBindingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _, skills, mcp_servers, repositories = await service.get_agent_detail(db, agent.id)
    return _to_detail(agent, skills, mcp_servers, repositories)


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_db_session)) -> AgentDetail:
    try:
        agent, skills, mcp_servers, repositories = await service.get_agent_detail(db, agent_id)
    except service.AgentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    return _to_detail(agent, skills, mcp_servers, repositories)


@router.put("/{agent_id}", response_model=AgentDetail)
async def update_agent(
    agent_id: UUID, body: AgentUpdateRequest, db: AsyncSession = Depends(get_db_session)
) -> AgentDetail:
    try:
        agent = await service.update_agent(
            db,
            agent_id,
            name=body.name.strip(),
            description=(body.description.strip() or None) if body.description else None,
            permission_mode=body.permission_mode,
            repo_refresh_interval_minutes=body.repo_refresh_interval_minutes,
            skill_ids=body.skill_ids,
            mcp_server_ids=body.mcp_server_ids,
            repositories=body.repositories,
        )
    except service.AgentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    except service.AgentNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.InvalidBindingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _, skills, mcp_servers, repositories = await service.get_agent_detail(db, agent.id)
    return _to_detail(agent, skills, mcp_servers, repositories)


@router.post("/{agent_id}/retry", response_model=AgentDetail)
async def retry_agent_init(agent_id: UUID, db: AsyncSession = Depends(get_db_session)) -> AgentDetail:
    try:
        agent = await service.retry_workspace_init(db, agent_id)
    except service.AgentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    except service.AgentNotFailedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    _, skills, mcp_servers, repositories = await service.get_agent_detail(db, agent.id)
    return _to_detail(agent, skills, mcp_servers, repositories)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, db: AsyncSession = Depends(get_db_session)) -> None:
    try:
        await service.delete_agent(db, agent_id)
    except service.AgentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
