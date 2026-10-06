import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.models import Conversation, Message
from app.schemas.common import UtcDatetime

MessageType = Literal["TEXT", "DOCUMENT_INFO", "FLIGHT_RESULTS", "HOTEL_RESULTS",
                      "BOOKING_CONFIRMATION", "BOOKING_STATUS", "CONFIRMATION_REQUEST",
                      "ERROR"]


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


class Source(BaseModel):
    type: Literal["document", "policy"]
    title: str
    document_id: str | None = None
    page: int | None = None
    section: str | None = None


class AssistantMessage(BaseModel):
    type: MessageType
    text: str
    sources: list[Source]
    cards: list[dict[str, Any]]


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: AssistantMessage
    agent: str


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    type: MessageType | None = None
    sources: list[Source] = []
    cards: list[dict[str, Any]] = []
    agent: str | None = None
    created_at: UtcDatetime

    @classmethod
    def from_message(cls, m: Message) -> "MessageOut":
        p = m.payload or {}
        return cls(id=m.id, role=m.role, text=m.content,  # type: ignore[arg-type]
                   type=p.get("type"), sources=p.get("sources", []),
                   cards=p.get("cards", []), agent=p.get("agent"), created_at=m.created_at)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    active_agent: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_conversation(cls, c: Conversation) -> "ConversationOut":
        return cls(id=c.id, title=c.title, active_agent=c.active_agent,
                   created_at=c.created_at, updated_at=c.updated_at)


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
