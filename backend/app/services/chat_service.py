"""Conversations with the assistant: storage, memory and one chat turn.

Memory: the model sees the conversation summary plus the last HISTORY_MESSAGES messages.
When more than SUMMARIZE_AT messages are not yet covered by the summary, the older ones
are folded into it with one `generate` call.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import supervisor
from app.agents.prompts import SUMMARY_PROMPT
from app.agents.tools import ToolContext
from app.core.errors import NotFoundError
from app.db.base import utcnow
from app.db.models import Conversation, Message, User
from app.services import audit_service
from app.services.llm_service import (
    ChatTurn,
    LLMError,
    LLMNotConfiguredError,
    LLMRateLimitedError,
    get_llm,
)

logger = logging.getLogger("travel.chat")

HISTORY_MESSAGES = 12
SUMMARIZE_AT = 20

ERROR_TEXT = {
    "not_configured": "The assistant isn't available right now. Please try again later.",
    "rate_limited": "The assistant is busy right now. Please try again in a minute.",
    "failed": "Sorry, I couldn't answer that right now. Please try again.",
}


class ChatService:
    def __init__(self, session: AsyncSession, user: User):
        self.session = session
        self.user = user

    async def conversations(self) -> list[Conversation]:
        return list((await self.session.execute(
            select(Conversation).where(Conversation.user_id == self.user.id)
            .order_by(Conversation.updated_at.desc()).limit(100)
        )).scalars())

    async def get(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = (await self.session.execute(
            select(Conversation).where(Conversation.id == conversation_id,
                                       Conversation.user_id == self.user.id)
        )).scalar_one_or_none()
        if conversation is None:  # another user's conversation is "not found" too
            raise NotFoundError("Conversation not found.")
        return conversation

    async def messages(self, conversation: Conversation) -> list[Message]:
        return list((await self.session.execute(
            select(Message).where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
        )).scalars())

    async def delete(self, conversation_id: uuid.UUID) -> None:
        conversation = await self.get(conversation_id)
        await self.session.delete(conversation)
        await audit_service.record(self.session, "chat.conversation_delete",
                                   user_id=self.user.id, resource_type="conversation",
                                   resource_id=str(conversation.id))
        await self.session.commit()

    async def send(self, conversation_id: uuid.UUID | None,
                   text: str) -> tuple[Conversation, Message]:
        if conversation_id:
            conversation = await self.get(conversation_id)
        else:
            title = " ".join(text.split())
            conversation = Conversation(user_id=self.user.id,
                                        title=title[:60] + ("…" if len(title) > 60 else ""))
            self.session.add(conversation)
            await self.session.flush()
        self.session.add(Message(conversation_id=conversation.id, role="user", content=text))
        conversation.updated_at = utcnow()
        await self.session.commit()  # keep the question even if answering fails

        agent = conversation.active_agent or "general"
        ctx = ToolContext(self.session, self.user, conversation.id)
        payload: dict[str, Any]
        try:
            history = await self._history(conversation)
            llm = get_llm()
            agent, intent = await supervisor.route(llm, history, conversation.active_agent)
            reply = await supervisor.run_agent(llm, ctx, agent, list(history),
                                               summary=conversation.summary, intent=intent)
            answer = reply.text
            is_document = any(s["type"] == "document" for s in ctx.sources)
            payload = {"type": "DOCUMENT_INFO" if is_document else "TEXT",
                       "sources": ctx.sources, "cards": [], "agent": agent}
            conversation.active_agent = agent
        except LLMError as exc:
            reason = ("not_configured" if isinstance(exc, LLMNotConfiguredError)
                      else "rate_limited" if isinstance(exc, LLMRateLimitedError) else "failed")
            logger.warning("chat turn failed", extra={"reason": reason, "error": str(exc)})
            answer = ERROR_TEXT[reason]
            payload = {"type": "ERROR", "sources": [], "cards": [], "agent": agent,
                       "error_code": reason}

        message = Message(conversation_id=conversation.id, role="assistant", content=answer,
                          payload=payload)
        self.session.add(message)
        conversation.updated_at = utcnow()
        await self.session.commit()
        return conversation, message

    async def _history(self, conversation: Conversation) -> list[ChatTurn]:
        """Recent messages for the model, summarising older ones when needed."""
        rows = [m for m in await self.messages(conversation) if m.role in ("user", "assistant")]
        pending = rows[conversation.summarized_count:]
        if len(pending) > SUMMARIZE_AT:
            older = pending[:-HISTORY_MESSAGES]
            try:
                conversation.summary = await self._summarize(conversation.summary, older)
                conversation.summarized_count += len(older)
            except LLMError as exc:  # keep going with the recent messages only
                logger.warning("summary failed", extra={"error": str(exc)})

        recent = rows[conversation.summarized_count:][-HISTORY_MESSAGES:]
        turns = [ChatTurn("user" if m.role == "user" else "model", m.content) for m in recent]
        while turns and turns[0].role != "user":  # the model expects a user turn first
            turns.pop(0)
        return turns

    async def _summarize(self, previous: str | None, messages: list[Message]) -> str:
        transcript = "\n".join(
            f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in messages)
        return await get_llm().generate(
            purpose="conversation_summary", system=SUMMARY_PROMPT,
            contents=[f"<previous_summary>\n{previous or '(none)'}\n</previous_summary>\n"
                      f"<conversation>\n{transcript}\n</conversation>"],
        )
