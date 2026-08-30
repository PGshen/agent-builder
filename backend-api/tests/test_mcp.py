import uuid

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.modules.mcp.masking import MASK_SENTINEL


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


async def test_mcp_endpoints_require_auth():
    async with await _client() as client:
        response = await client.get("/mcp")
    assert response.status_code == 401


async def test_create_stdio_mcp_missing_command_rejected():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/mcp",
            json={"name": f"bad-mcp-{uuid.uuid4().hex[:8]}", "config": {"type": "stdio"}},
            headers=headers,
        )
    assert response.status_code == 422


async def test_stdio_mcp_lifecycle_with_env_masking():
    name = f"stdio-mcp-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        create_response = await client.post(
            "/mcp",
            json={
                "name": name,
                "config": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "some-mcp-server"],
                    "env": {"API_KEY": "super-secret"},
                },
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        mcp_id = created["id"]
        assert created["config"]["env"]["API_KEY"] == MASK_SENTINEL

        list_response = await client.get("/mcp", headers=headers)
        assert any(item["id"] == mcp_id for item in list_response.json())

        detail_response = await client.get(f"/mcp/{mcp_id}", headers=headers)
        detail = detail_response.json()
        assert detail["config"]["command"] == "npx"
        assert detail["config"]["env"]["API_KEY"] == MASK_SENTINEL

        # 保存时 env 值仍是打码占位符（前端没有重新输入）：应保留原始密钥不变
        update_unchanged = await client.put(
            f"/mcp/{mcp_id}",
            json={
                "name": name,
                "config": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "some-mcp-server", "--verbose"],
                    "env": {"API_KEY": MASK_SENTINEL},
                },
                "status": "active",
            },
            headers=headers,
        )
        assert update_unchanged.status_code == 200
        assert update_unchanged.json()["config"]["args"] == ["-y", "some-mcp-server", "--verbose"]
        assert update_unchanged.json()["config"]["env"]["API_KEY"] == MASK_SENTINEL

        # 重新输入了新的 env 值：应该真正更新（用后门方式解密确认，因为 API 层永远只返回打码值）
        from app.db import get_session_factory
        from app.modules.mcp import service as mcp_service

        update_changed = await client.put(
            f"/mcp/{mcp_id}",
            json={
                "name": name,
                "config": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "some-mcp-server", "--verbose"],
                    "env": {"API_KEY": "rotated-secret"},
                },
                "status": "active",
            },
            headers=headers,
        )
        assert update_changed.status_code == 200

        session_factory = get_session_factory()
        async with session_factory() as db:
            _, decrypted = await mcp_service.get_mcp_server_detail(db, uuid.UUID(mcp_id))
        assert decrypted["env"]["API_KEY"] == "rotated-secret"

        delete_response = await client.delete(f"/mcp/{mcp_id}", headers=headers)
        assert delete_response.status_code == 204

        get_after_delete = await client.get(f"/mcp/{mcp_id}", headers=headers)
        assert get_after_delete.status_code == 404


async def test_http_mcp_with_headers_and_duplicate_name():
    name = f"http-mcp-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        first = await client.post(
            "/mcp",
            json={
                "name": name,
                "config": {
                    "type": "http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer token-123"},
                },
            },
            headers=headers,
        )
        assert first.status_code == 201
        mcp_id = first.json()["id"]
        assert first.json()["config"]["headers"]["Authorization"] == MASK_SENTINEL

        second = await client.post(
            "/mcp",
            json={"name": name, "config": {"type": "http", "url": "https://example.com/mcp"}},
            headers=headers,
        )
        assert second.status_code == 409

        await client.delete(f"/mcp/{mcp_id}", headers=headers)
