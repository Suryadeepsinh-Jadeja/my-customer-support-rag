"""All ORM models, imported here so Alembic and `Base.metadata` see every table."""

from app.db.models.audit import AuditLog
from app.db.models.booking import (
    Booking,
    BookingKind,
    BookingStatus,
    ConfirmationRequest,
    ConfirmationStatus,
)
from app.db.models.chat import Conversation, Message, ToolExecution
from app.db.models.document import (
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentType,
    ExtractedEntity,
    JobStatus,
    ProcessingJob,
)
from app.db.models.rag import DocumentChunk, KnowledgeChunk, KnowledgeDocument
from app.db.models.user import CabinClass, Role, TravelPreference, User, UserProfile

__all__ = [
    "AuditLog",
    "Booking",
    "BookingKind",
    "BookingStatus",
    "CabinClass",
    "ConfirmationRequest",
    "ConfirmationStatus",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentPage",
    "DocumentStatus",
    "DocumentType",
    "ExtractedEntity",
    "JobStatus",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Message",
    "ProcessingJob",
    "Role",
    "ToolExecution",
    "TravelPreference",
    "User",
    "UserProfile",
]
