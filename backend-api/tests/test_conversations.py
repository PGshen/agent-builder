import uuid

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import get_session_factory
from app.main import app
from app.modules.agents.models import Agent
from app.modules.conversations import router as router_module
from app.modules.conversations.runner_client import RunnerRequestError


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


async def _create_agent() -> uuid.UUID:
    session_factory = get_session_factory()
    async with session_factory() as db:
        agent = Agent(name=f"conv-test-agent-{uuid.uuid4().hex[:8]}", status="ready")
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        return agent.id


class _FakeUpstream:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.closed = False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self):
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_conversation_endpoints_require_auth():
    async with await _client() as client:
        agent_id = uuid.uuid4()
        assert (await client.post(f"/agents/{agent_id}/conversations")).status_code == 401
        assert (await client.get(f"/conversations/{uuid.uuid4()}")).status_code == 401
        assert (
            await client.post(f"/conversations/{uuid.uuid4()}/messages", json={"prompt": "hi"})
        ).status_code == 401


async def test_create_conversation_returns_404_for_unknown_agent():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(f"/agents/{uuid.uuid4()}/conversations", headers=headers)
        assert response.status_code == 404


async def test_create_and_get_conversation():
    agent_id = await _create_agent()
    async with await _client() as client:
        headers = await _auth_headers(client)
        create_resp = await client.post(f"/agents/{agent_id}/conversations", headers=headers)
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["agent_id"] == str(agent_id)
        assert body["session_id"] is None
        assert body["status"] == "active"

        get_resp = await client.get(f"/conversations/{body['id']}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json() == body


async def test_get_conversation_returns_404_for_unknown_id():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.get(f"/conversations/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404


async def test_send_message_streams_and_saves_session_id_for_resume(monkeypatch):
    agent_id = await _create_agent()
    async with await _client() as client:
        headers = await _auth_headers(client)
        conversation_id = (
            await client.post(f"/agents/{agent_id}/conversations", headers=headers)
        ).json()["id"]

        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        lines = [
            'data: {"type": "AssistantMessage", "content": []}',
            "",
            f'data: {{"type": "ResultMessage", "session_id": "{session_id}"}}',
            "",
        ]
        seen_resume_ids: list[str | None] = []

        async def _fake_open(client_arg, agent_id_arg, prompt, resume_session_id):
            seen_resume_ids.append(resume_session_id)
            assert str(agent_id_arg) == str(agent_id)
            return _FakeUpstream(lines)

        monkeypatch.setattr(router_module, "build_client", lambda: _FakeClient())
        monkeypatch.setattr(router_module, "open_execute_stream", _fake_open)

        response = await client.post(
            f"/conversations/{conversation_id}/messages", headers=headers, json={"prompt": "hi"}
        )
        assert response.status_code == 200
        assert session_id in response.text

        detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
        assert detail.json()["session_id"] == session_id

        # 第二轮：应该带上第一轮存下来的 session_id 续接
        response2 = await client.post(
            f"/conversations/{conversation_id}/messages", headers=headers, json={"prompt": "again"}
        )
        assert response2.status_code == 200

    assert seen_resume_ids == [None, session_id]


async def test_send_message_propagates_agent_busy_as_409(monkeypatch):
    agent_id = await _create_agent()
    async with await _client() as client:
        headers = await _auth_headers(client)
        conversation_id = (
            await client.post(f"/agents/{agent_id}/conversations", headers=headers)
        ).json()["id"]

        async def _fake_open_busy(client_arg, agent_id_arg, prompt, resume_session_id):
            raise RunnerRequestError(409, f"Agent {agent_id_arg} 正忙，请稍后再试")

        monkeypatch.setattr(router_module, "build_client", lambda: _FakeClient())
        monkeypatch.setattr(router_module, "open_execute_stream", _fake_open_busy)

        response = await client.post(
            f"/conversations/{conversation_id}/messages", headers=headers, json={"prompt": "hi"}
        )
        assert response.status_code == 409
        assert "正忙" in response.json()["detail"]


async def test_send_message_returns_404_for_unknown_conversation():
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(
            f"/conversations/{uuid.uuid4()}/messages", headers=headers, json={"prompt": "hi"}
        )
        assert response.status_code == 404
