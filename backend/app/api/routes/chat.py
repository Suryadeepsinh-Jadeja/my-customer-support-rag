import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import rate_limit
from app.db.database import get_db
from app.db.models import User
from app.schemas.chat import (
    AssistantMessage,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])

CHAT_RATE_LIMIT_PER_MINUTE = 30


@router.post("/chat", response_model=ChatResponse, summary="Ask the travel assistant")
async def chat(body: ChatRequest, user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """Starts a conversation when `conversation_id` is omitted. Answers use your documents,
    the policy knowledge base and your profile, with the sources they came from."""
    rate_limit.enforce("chat", str(user.id), CHAT_RATE_LIMIT_PER_MINUTE, 60)
    conversation, message = await ChatService(db, user).send(body.conversation_id,
                                                             body.message)
    p = message.payload
    return ChatResponse(
        conversation_id=conversation.id, agent=p["agent"],
        message=AssistantMessage(type=p["type"], text=message.content,
                                 sources=p["sources"], cards=p["cards"]),
    )


@router.get("/conversations", response_model=list[ConversationOut],
            summary="Your conversations, most recent first")
async def list_conversations(user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    conversations = await ChatService(db, user).conversations()
    return [ConversationOut.from_conversation(c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail,
            summary="A conversation with its messages")
async def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    service = ChatService(db, user)
    conversation = await service.get(conversation_id)
    messages = await service.messages(conversation)
    return ConversationDetail(
        **ConversationOut.from_conversation(conversation).model_dump(),
        messages=[MessageOut.from_message(m) for m in messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a conversation and its messages")
async def delete_conversation(conversation_id: uuid.UUID,
                              user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    await ChatService(db, user).delete(conversation_id)
