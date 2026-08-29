from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_me_without_token_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_login_with_wrong_password_is_unauthorized():
    async with await _client() as client:
        response = await client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401


async def test_login_then_me_then_logout_invalidates_token():
    settings = get_settings()
    async with await _client() as client:
        login_response = await client.post(
            "/auth/login",
            json={"username": settings.admin_username, "password": settings.admin_password},
        )
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        assert login_response.json()["expires_in"] == settings.auth_token_ttl_seconds

        me_response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["username"] == settings.admin_username

        logout_response = await client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout_response.status_code == 204

        me_after_logout = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_after_logout.status_code == 401


async def test_me_with_bogus_token_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
