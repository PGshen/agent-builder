from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_endpoint_reports_database_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()
    assert response.status_code in (200, 503)
    assert body["status"] in ("ok", "degraded")
    assert "connected" in body["dependencies"]["database"]
