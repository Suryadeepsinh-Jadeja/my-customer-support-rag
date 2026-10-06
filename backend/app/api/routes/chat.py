import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.bookings import BOOKING_RATE_LIMIT_PER_MINUTE
from app.core import rate_limit
from app.db.database import get_db
from app.db.models import User
from app.schemas.booking import BookingOut, ConfirmRequest, ConfirmResponse
from app.schemas.chat import (
    AssistantMessage,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services.booking_service import BookingService, booking_card
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


@router.post("/chat/confirm", response_model=ConfirmResponse,
             summary="Approve or decline a booking, change or cancellation")
async def confirm(body: ConfirmRequest, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    """The only way a sensitive action runs. The request must belong to you, still be
    pending and not have expired (10 minutes); each one can be used once."""
    rate_limit.enforce("booking", str(user.id), BOOKING_RATE_LIMIT_PER_MINUTE, 60)
    outcome = await BookingService(db, user).confirm(body.confirmation_id, body.approved)
    booking = outcome.booking
    return ConfirmResponse(
        confirmation_id=outcome.confirmation.id, status=outcome.confirmation.status.value,
        message=AssistantMessage(type=outcome.message_type,  # type: ignore[arg-type]
                                 text=outcome.text, sources=[],
                                 cards=[booking_card(booking)] if booking else []),
        booking=BookingOut.from_booking(booking) if booking else None,
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
