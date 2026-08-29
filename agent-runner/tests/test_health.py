from httpx import ASGITransport, AsyncClient

from app.server.main import app


async def test_health_endpoint_reports_dependency_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()
    assert response.status_code in (200, 503)
    assert body["status"] in ("ok", "degraded")
    deps = body["dependencies"]
    assert "connected" in deps["postgres"]
    assert "connected" in deps["redis"]
    assert "connected" in deps["minio"]
    assert "writable" in deps["local_cache"]
