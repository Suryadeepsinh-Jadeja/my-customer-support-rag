import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, str_enum


class DocumentStatus(enum.StrEnum):
    QUEUED = "queued"          # stored, waiting for the worker
    PROCESSING = "processing"
    EXTRACTED = "extracted"    # text + fields extracted (indexing for the assistant: phase 3)
    FAILED = "failed"          # could not be processed; can be retried
    REJECTED = "rejected"      # failed the malware scan; file removed


class DocumentType(enum.StrEnum):
    PASSPORT = "passport"
    VISA = "visa"
    FLIGHT_TICKET = "flight_ticket"
    BOARDING_PASS = "boarding_pass"  # noqa: S105 (not a password)
    HOTEL_BOOKING = "hotel_booking"
    CAR_BOOKING = "car_booking"
    INSURANCE = "insurance"
    ITINERARY = "itinerary"
    IDENTITY_DOCUMENT = "identity_document"
    OTHER = "other"


class Document(UUIDPk, Timestamps, Base):
    """An uploaded file. Always owned by exactly one user; every query filters on user_id."""

    __tablename__ = "documents"
    __table_args__ = (
        # The same file can only be uploaded once per user.
        UniqueConstraint("user_id", "sha256", name="uq_documents_user_sha256"),
        Index("ix_documents_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))  # detected from the bytes
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)

    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus, "document_status"), default=DocumentStatus.QUEUED, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64))

    document_type: Mapped[DocumentType | None] = mapped_column(
        str_enum(DocumentType, "document_type")
    )
    type_confidence: Mapped[float | None] = mapped_column(Float)
    analysis_method: Mapped[str | None] = mapped_column(String(16))  # gemini | rules
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)

    # Pipeline progress (shown as a checklist in the UI)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fields_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True,
        order_by="DocumentPage.page_number",
    )
    entities: Mapped[list["ExtractedEntity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True,
        order_by="(ExtractedEntity.group_index, ExtractedEntity.id)",
    )


class DocumentPage(Base):
    """Extracted text per page, kept so answers can cite the page they came from."""

    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[Document] = relationship(back_populates="pages")


class ExtractedEntity(Base):
    """One extracted field, with where it came from and how sure we are.

    Values are evidence from a document, not verified truth: the source document, page,
    method and confidence travel with every value.
    """

    __tablename__ = "extracted_entities"
    __table_args__ = (Index("ix_extracted_entities_user_field", "user_id", "field"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # Denormalised owner so entity lookups can filter by user without a join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(32))  # the document type it belongs to
    field: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(1000))
    # Groups repeated structures, e.g. each flight segment of an itinerary.
    group_index: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(16))  # gemini | rules | mrz
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="entities")


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProcessingJob(UUIDPk, Timestamps, Base):
    """Database-backed job queue (no extra infrastructure; safe with several workers)."""

    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_processing_jobs_pick", "status", "run_after"),)

    kind: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"),
                                              default=JobStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # An error code only; never document content.
    last_error: Mapped[str | None] = mapped_column(String(200))
