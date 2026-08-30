import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import masking, tasks
from app.modules.agents.models import Agent, AgentMCPServer, AgentRepository, AgentSkill
from app.modules.agents.schemas import AgentRepositoryInput
from app.modules.mcp.models import MCPServerConfig
from app.modules.skills.models import Skill


class AgentNotFoundError(Exception):
    pass


class AgentNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Agent 名称已存在：{name}")


class InvalidBindingError(Exception):
    """创建/编辑时绑定了不存在的 skill 或 MCP server。"""

    def __init__(self, missing_skill_ids: list[uuid.UUID], missing_mcp_server_ids: list[uuid.UUID]) -> None:
        self.missing_skill_ids = missing_skill_ids
        self.missing_mcp_server_ids = missing_mcp_server_ids
        parts = []
        if missing_skill_ids:
            parts.append(f"不存在的 skill_ids：{', '.join(str(i) for i in missing_skill_ids)}")
        if missing_mcp_server_ids:
            parts.append(f"不存在的 mcp_server_ids：{', '.join(str(i) for i in missing_mcp_server_ids)}")
        super().__init__("；".join(parts))


@dataclass
class AgentListEntry:
    agent: Agent
    skill_count: int
    mcp_server_count: int
    repository_count: int


async def _get_agent_or_raise(db: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFoundError(str(agent_id))
    return agent


async def _validate_bindings(
    db: AsyncSession, skill_ids: list[uuid.UUID], mcp_server_ids: list[uuid.UUID]
) -> None:
    missing_skill_ids: list[uuid.UUID] = []
    if skill_ids:
        found = set((await db.execute(select(Skill.id).where(Skill.id.in_(skill_ids)))).scalars())
        missing_skill_ids = [i for i in skill_ids if i not in found]

    missing_mcp_server_ids: list[uuid.UUID] = []
    if mcp_server_ids:
        found = set(
            (await db.execute(select(MCPServerConfig.id).where(MCPServerConfig.id.in_(mcp_server_ids)))).scalars()
        )
        missing_mcp_server_ids = [i for i in mcp_server_ids if i not in found]

    if missing_skill_ids or missing_mcp_server_ids:
        raise InvalidBindingError(missing_skill_ids, missing_mcp_server_ids)


async def list_agents(db: AsyncSession) -> list[AgentListEntry]:
    agents = list((await db.execute(select(Agent).order_by(Agent.name))).scalars())
    if not agents:
        return []
    agent_ids = [agent.id for agent in agents]

    skill_counts = dict(
        (
            await db.execute(
                select(AgentSkill.agent_id, func.count())
                .where(AgentSkill.agent_id.in_(agent_ids))
                .group_by(AgentSkill.agent_id)
            )
        ).all()
    )
    mcp_counts = dict(
        (
            await db.execute(
                select(AgentMCPServer.agent_id, func.count())
                .where(AgentMCPServer.agent_id.in_(agent_ids))
                .group_by(AgentMCPServer.agent_id)
            )
        ).all()
    )
    repo_counts = dict(
        (
            await db.execute(
                select(AgentRepository.agent_id, func.count())
                .where(AgentRepository.agent_id.in_(agent_ids))
                .group_by(AgentRepository.agent_id)
            )
        ).all()
    )

    return [
        AgentListEntry(
            agent=agent,
            skill_count=skill_counts.get(agent.id, 0),
            mcp_server_count=mcp_counts.get(agent.id, 0),
            repository_count=repo_counts.get(agent.id, 0),
        )
        for agent in agents
    ]


async def get_agent_detail(
    db: AsyncSession, agent_id: uuid.UUID
) -> tuple[Agent, list[Skill], list[MCPServerConfig], list[AgentRepository]]:
    agent = await _get_agent_or_raise(db, agent_id)

    skills = list(
        (
            await db.execute(
                select(Skill)
                .join(AgentSkill, AgentSkill.skill_id == Skill.id)
                .where(AgentSkill.agent_id == agent_id)
                .order_by(Skill.name)
            )
        ).scalars()
    )
    mcp_servers = list(
        (
            await db.execute(
                select(MCPServerConfig)
                .join(AgentMCPServer, AgentMCPServer.mcp_server_id == MCPServerConfig.id)
                .where(AgentMCPServer.agent_id == agent_id)
                .order_by(MCPServerConfig.name)
            )
        ).scalars()
    )
    repositories = list(
        (
            await db.execute(
                select(AgentRepository)
                .where(AgentRepository.agent_id == agent_id)
                .order_by(AgentRepository.position)
            )
        ).scalars()
    )
    return agent, skills, mcp_servers, repositories


async def create_agent(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
    permission_mode: str,
    repo_refresh_interval_minutes: int,
    skill_ids: list[uuid.UUID],
    mcp_server_ids: list[uuid.UUID],
    repositories: list[AgentRepositoryInput],
) -> Agent:
    await _validate_bindings(db, skill_ids, mcp_server_ids)

    agent = Agent(
        name=name,
        description=description,
        permission_mode=permission_mode,
        repo_refresh_interval_minutes=repo_refresh_interval_minutes,
        status="initializing",
    )
    db.add(agent)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AgentNameConflictError(name) from exc

    for skill_id in skill_ids:
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill_id))
    for mcp_server_id in mcp_server_ids:
        db.add(AgentMCPServer(agent_id=agent.id, mcp_server_id=mcp_server_id))
    for position, repo in enumerate(repositories):
        credential_encrypted = masking.resolve_credential_encrypted(
            existing=None, auth_type=repo.auth_type, submitted_credential=repo.auth_credential
        )
        db.add(
            AgentRepository(
                agent_id=agent.id,
                url=repo.url,
                branch=repo.branch,
                auth_type=repo.auth_type,
                auth_credential=credential_encrypted,
                position=position,
            )
        )

    await db.commit()
    await db.refresh(agent)

    tasks.trigger_workspace_init(str(agent.id))
    return agent


async def update_agent(
    db: AsyncSession,
    agent_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
    permission_mode: str,
    repo_refresh_interval_minutes: int,
    skill_ids: list[uuid.UUID],
    mcp_server_ids: list[uuid.UUID],
    repositories: list[AgentRepositoryInput],
) -> Agent:
    agent = await _get_agent_or_raise(db, agent_id)
    await _validate_bindings(db, skill_ids, mcp_server_ids)

    existing_repos = {
        repo.id: repo
        for repo in (
            await db.execute(select(AgentRepository).where(AgentRepository.agent_id == agent_id))
        ).scalars()
    }

    agent.name = name
    agent.description = description
    agent.permission_mode = permission_mode
    agent.repo_refresh_interval_minutes = repo_refresh_interval_minutes

    await db.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent_id))
    await db.execute(delete(AgentMCPServer).where(AgentMCPServer.agent_id == agent_id))
    await db.execute(delete(AgentRepository).where(AgentRepository.agent_id == agent_id))

    for skill_id in skill_ids:
        db.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))
    for mcp_server_id in mcp_server_ids:
        db.add(AgentMCPServer(agent_id=agent_id, mcp_server_id=mcp_server_id))
    for position, repo in enumerate(repositories):
        existing = existing_repos.get(repo.id) if repo.id is not None else None
        credential_encrypted = masking.resolve_credential_encrypted(
            existing=existing, auth_type=repo.auth_type, submitted_credential=repo.auth_credential
        )
        db.add(
            AgentRepository(
                agent_id=agent_id,
                url=repo.url,
                branch=repo.branch,
                auth_type=repo.auth_type,
                auth_credential=credential_encrypted,
                position=position,
            )
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AgentNameConflictError(name) from exc
    await db.refresh(agent)
    return agent


async def delete_agent(db: AsyncSession, agent_id: uuid.UUID) -> None:
    agent = await _get_agent_or_raise(db, agent_id)
    await db.delete(agent)
    await db.commit()
