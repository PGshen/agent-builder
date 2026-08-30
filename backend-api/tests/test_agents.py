import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session_factory
from app.main import app
from app.modules.agents.masking import MASK_SENTINEL
from app.modules.agents.models import Agent, AgentRepository
from app.modules.agents import crypto as agent_crypto
from app.modules.mcp import crypto as mcp_crypto
from app.modules.mcp.models import MCPServerConfig
from app.modules.skills.models import Skill


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    settings = get_settings()
    response = await client.post(
        "/auth/login",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_skill_and_mcp() -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    session_factory = get_session_factory()
    async with session_factory() as db:
        skill = Skill(
            name=f"agent-test-skill-{suffix}",
            object_key=f"agent-test-skill-{suffix}/v1.zip",
            version=1,
            active_version=1,
            versions=[],
            status="active",
        )
        mcp_server = MCPServerConfig(
            name=f"agent-test-mcp-{suffix}",
            config_encrypted=mcp_crypto.encrypt_config({"type": "stdio", "command": "npx", "args": [], "env": {}}),
            status="active",
        )
        db.add(skill)
        db.add(mcp_server)
        await db.commit()
        await db.refresh(skill)
        await db.refresh(mcp_server)
        return skill.id, mcp_server.id


async def test_agent_endpoints_require_auth():
    async with await _client() as client:
        response = await client.get("/agents")
    assert response.status_code == 401


async def test_create_agent_missing_name_rejected():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post("/agents", json={}, headers=headers)
    assert response.status_code == 422


async def test_create_agent_with_unknown_bindings_rejected():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/agents",
            json={
                "name": f"agent-bad-binding-{uuid.uuid4().hex[:8]}",
                "skill_ids": [str(uuid.uuid4())],
            },
            headers=headers,
        )
    assert response.status_code == 400


async def test_agent_lifecycle_with_bindings_and_repo_credential_masking():
    skill_id, mcp_server_id = await _create_skill_and_mcp()
    name = f"agent-lifecycle-{uuid.uuid4().hex[:8]}"

    async with await _client() as client:
        headers = await _auth_headers(client)

        create_response = await client.post(
            "/agents",
            json={
                "name": name,
                "permission_mode": "default",
                "repo_refresh_interval_minutes": 15,
                "skill_ids": [str(skill_id)],
                "mcp_server_ids": [str(mcp_server_id)],
                "repositories": [
                    {"url": "https://example.com/repo.git", "branch": "main", "auth_type": "token", "auth_credential": "super-secret-token"}
                ],
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        agent_id = created["id"]
        assert created["status"] == "initializing"
        assert created["workspace_id"]
        assert [s["id"] for s in created["skills"]] == [str(skill_id)]
        assert [m["id"] for m in created["mcp_servers"]] == [str(mcp_server_id)]
        assert len(created["repositories"]) == 1
        repo = created["repositories"][0]
        assert repo["auth_credential"] == MASK_SENTINEL
        repo_id = repo["id"]

        # 列表页能看到正确的绑定数量
        list_response = await client.get("/agents", headers=headers)
        entry = next(item for item in list_response.json() if item["id"] == agent_id)
        assert entry["skill_count"] == 1
        assert entry["mcp_server_count"] == 1
        assert entry["repository_count"] == 1

        detail_response = await client.get(f"/agents/{agent_id}", headers=headers)
        detail = detail_response.json()
        assert detail["repositories"][0]["auth_credential"] == MASK_SENTINEL

        # 编辑时凭证仍是打码占位符：应保留原始密钥不变，只更新 branch
        update_unchanged = await client.put(
            f"/agents/{agent_id}",
            json={
                "name": name,
                "permission_mode": "default",
                "repo_refresh_interval_minutes": 15,
                "skill_ids": [str(skill_id)],
                "mcp_server_ids": [str(mcp_server_id)],
                "repositories": [
                    {
                        "id": repo_id,
                        "url": "https://example.com/repo.git",
                        "branch": "develop",
                        "auth_type": "token",
                        "auth_credential": MASK_SENTINEL,
                    }
                ],
            },
            headers=headers,
        )
        assert update_unchanged.status_code == 200
        updated = update_unchanged.json()
        new_repo_id = updated["repositories"][0]["id"]
        assert updated["repositories"][0]["branch"] == "develop"
        assert updated["repositories"][0]["auth_credential"] == MASK_SENTINEL

        session_factory = get_session_factory()
        async with session_factory() as db:
            row = (
                await db.execute(select(AgentRepository).where(AgentRepository.id == uuid.UUID(new_repo_id)))
            ).scalar_one()
            assert agent_crypto.decrypt_credential(row.auth_credential) == "super-secret-token"

        # 重新输入了新凭证：应该真正更新
        update_changed = await client.put(
            f"/agents/{agent_id}",
            json={
                "name": name,
                "permission_mode": "default",
                "repo_refresh_interval_minutes": 15,
                "skill_ids": [],
                "mcp_server_ids": [],
                "repositories": [
                    {
                        "id": new_repo_id,
                        "url": "https://example.com/repo.git",
                        "branch": "develop",
                        "auth_type": "token",
                        "auth_credential": "rotated-secret",
                    }
                ],
            },
            headers=headers,
        )
        assert update_changed.status_code == 200
        assert update_changed.json()["skills"] == []
        assert update_changed.json()["mcp_servers"] == []
        rotated_repo_id = update_changed.json()["repositories"][0]["id"]

        async with session_factory() as db:
            row = (
                await db.execute(select(AgentRepository).where(AgentRepository.id == uuid.UUID(rotated_repo_id)))
            ).scalar_one()
            assert agent_crypto.decrypt_credential(row.auth_credential) == "rotated-secret"

        delete_response = await client.delete(f"/agents/{agent_id}", headers=headers)
        assert delete_response.status_code == 204

        get_after_delete = await client.get(f"/agents/{agent_id}", headers=headers)
        assert get_after_delete.status_code == 404


async def test_update_agent_retriggers_init_only_when_repos_changed():
    name = f"agent-put-retrigger-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        created = await client.post(
            "/agents",
            json={
                "name": name,
                "repositories": [
                    {"url": "https://example.com/repo.git", "branch": "main", "auth_type": "none"}
                ],
            },
            headers=headers,
        )
        assert created.status_code == 201
        payload = created.json()
        agent_id = payload["id"]
        repo_id = payload["repositories"][0]["id"]

        # 模拟 T2.3 worker 已经跑完初始化（真实场景由 Runner 写入 ready）
        session_factory = get_session_factory()
        async with session_factory() as db:
            agent = await db.get(Agent, uuid.UUID(agent_id))
            agent.status = "ready"
            await db.commit()

        # 仓库列表原样不变（url/branch/auth_type 都一样）：不应该把 ready 重置为 initializing
        put_unchanged = await client.put(
            f"/agents/{agent_id}",
            json={
                "name": name,
                "repositories": [
                    {
                        "id": repo_id,
                        "url": "https://example.com/repo.git",
                        "branch": "main",
                        "auth_type": "none",
                    }
                ],
            },
            headers=headers,
        )
        assert put_unchanged.status_code == 200
        assert put_unchanged.json()["status"] == "ready"

        # 改了仓库 branch：视为仓库绑定发生变化，应该自动重新触发初始化（状态回到 initializing）
        put_changed = await client.put(
            f"/agents/{agent_id}",
            json={
                "name": name,
                "repositories": [
                    {
                        "id": repo_id,
                        "url": "https://example.com/repo.git",
                        "branch": "develop",
                        "auth_type": "none",
                    }
                ],
            },
            headers=headers,
        )
        assert put_changed.status_code == 200
        assert put_changed.json()["status"] == "initializing"
        assert put_changed.json()["status_message"] is None

        await client.delete(f"/agents/{agent_id}", headers=headers)


async def test_retry_init_requires_failed_status():
    name = f"agent-retry-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        created = await client.post("/agents", json={"name": name}, headers=headers)
        assert created.status_code == 201
        agent_id = created.json()["id"]
        assert created.json()["status"] == "initializing"

        # 当前是 initializing，不允许重试
        retry_while_initializing = await client.post(f"/agents/{agent_id}/retry", headers=headers)
        assert retry_while_initializing.status_code == 409

        # 直接改数据库模拟"已失败"状态（真实场景由 T2.3 Runner 任务写入）
        session_factory = get_session_factory()
        async with session_factory() as db:
            agent = await db.get(Agent, uuid.UUID(agent_id))
            agent.status = "failed"
            agent.status_message = "clone 失败：仓库地址不可达"
            await db.commit()

        retry_response = await client.post(f"/agents/{agent_id}/retry", headers=headers)
        assert retry_response.status_code == 200
        retried = retry_response.json()
        assert retried["status"] == "initializing"
        assert retried["status_message"] is None

        await client.delete(f"/agents/{agent_id}", headers=headers)


async def test_retry_init_missing_agent_returns_404():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(f"/agents/{uuid.uuid4()}/retry", headers=headers)
    assert response.status_code == 404


async def test_duplicate_agent_name_rejected():
    name = f"agent-dup-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        first = await client.post("/agents", json={"name": name}, headers=headers)
        assert first.status_code == 201

        second = await client.post("/agents", json={"name": name}, headers=headers)
        assert second.status_code == 409

        await client.delete(f"/agents/{first.json()['id']}", headers=headers)
