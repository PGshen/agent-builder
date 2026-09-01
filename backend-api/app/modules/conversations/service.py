"""Conversation Service（TASKS.md T4.5）：维护 `conversation_id ↔ (agent_id, session_id)` 映射。

发起/续接对话本身（直连调用 Runner、转发 SSE）在 `router.py` 里用独立的 DB session 处理，
不经过这里——本模块只负责 conversation 记录的增删查。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.conversations.models import Conversation


class AgentNotFoundError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


async def create_conversation(db: AsyncSession, agent_id: uuid.UUID) -> Conversation:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFoundError(str(agent_id))

    conversation = Conversation(agent_id=agent_id, session_id=None, status="active")
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(str(conversation_id))
    return conversation
