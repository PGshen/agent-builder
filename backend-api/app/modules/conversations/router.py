"""Conversation Service 对外接口（TASKS.md T4.5）：
- `POST /agents/{agent_id}/conversations`：新建对话（`session_id` 为空）
- `GET /conversations/{conversation_id}`：查询对话（含 `session_id`），供前端刷新页面后判断能否续接
- `POST /conversations/{conversation_id}/messages`：发一轮消息，SSE 转发 Runner 的实时流式输出，
  流结束后从 `ResultMessage` 里取 `session_id` 回写（首次执行成功后才有值，之后每轮覆盖更新）
"""

import json
import uuid
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import get_current_admin, get_db_session
from app.db import get_session_factory
from app.logging_config import get_logger
from app.modules.conversations import service
from app.modules.conversations.models import Conversation
from app.modules.conversations.runner_client import RunnerRequestError, build_client, open_execute_stream
from app.modules.conversations.schemas import ConversationDetail, SendMessageRequest

router = APIRouter(tags=["conversations"], dependencies=[Depends(get_current_admin)])
logger = get_logger(__name__)


def _to_detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail.model_validate(conversation)


@router.post(
    "/agents/{agent_id}/conversations",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> ConversationDetail:
    try:
        conversation = await service.create_conversation(db, agent_id)
    except service.AgentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    return _to_detail(conversation)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> ConversationDetail:
    try:
        conversation = await service.get_conversation(db, conversation_id)
    except service.ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="对话不存在") from exc
    return _to_detail(conversation)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: uuid.UUID, body: SendMessageRequest) -> StreamingResponse:
    # 用独立 DB session 查一次 conversation，取完 agent_id/session_id 就关闭——不把它带进下面的
    # 长生命周期流式响应里（同 agent-runner 的一贯模式：不长期占用一个连接/session）
    session_factory = get_session_factory()
    async with session_factory() as db:
        try:
            conversation = await service.get_conversation(db, conversation_id)
        except service.ConversationNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="对话不存在") from exc
        agent_id = conversation.agent_id
        resume_session_id = conversation.session_id

    client = build_client()
    try:
        upstream = await open_execute_stream(client, agent_id, body.prompt, resume_session_id)
    except RunnerRequestError as exc:
        await client.aclose()
        raise HTTPException(exc.status_code, detail=exc.detail) from exc

    return StreamingResponse(
        _forward_stream(upstream, client, conversation_id), media_type="text/event-stream"
    )


async def _forward_stream(
    upstream: httpx.Response, client: httpx.AsyncClient, conversation_id: uuid.UUID
) -> AsyncIterator[str]:
    session_id: str | None = None
    try:
        async for line in upstream.aiter_lines():
            if line.startswith("data: "):
                session_id = _extract_session_id(line[len("data: ") :]) or session_id
            yield f"{line}\n"
    finally:
        await upstream.aclose()
        await client.aclose()
        if session_id is not None:
            await _save_session_id(conversation_id, session_id)


def _extract_session_id(payload: str) -> str | None:
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(event, dict) and event.get("type") == "ResultMessage":
        return event.get("session_id")
    return None


async def _save_session_id(conversation_id: uuid.UUID, session_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            return
        if conversation.session_id != session_id:
            conversation.session_id = session_id
            await db.commit()
        logger.info(
            "conversation_session_saved", conversation_id=str(conversation_id), session_id=session_id
        )
