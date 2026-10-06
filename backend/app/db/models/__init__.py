"""All ORM models, imported here so Alembic and `Base.metadata` see every table."""

from app.db.models.audit import AuditLog
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
    "CabinClass",
    "Document",
    "DocumentChunk",
    "DocumentPage",
    "DocumentStatus",
    "DocumentType",
    "ExtractedEntity",
    "JobStatus",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "ProcessingJob",
    "Role",
    "TravelPreference",
    "User",
    "UserProfile",
]
