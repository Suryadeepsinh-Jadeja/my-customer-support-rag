"""Chunks of user documents and of the knowledge base, with their embeddings."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, bindparam
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, Timestamps, UUIDPk, utcnow

EMBEDDING_DIM = 768


class Embedding(TypeDecorator):
    """pgvector on PostgreSQL; JSON elsewhere (SQLite in development and tests)."""

    impl = JSON(none_as_null=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_result_value(self, value, dialect):
        return None if value is None else [float(x) for x in value]

    class comparator_factory(TypeDecorator.Comparator):  # noqa: N801 (SQLAlchemy API)
        def cosine_distance(self, other):
            return self.expr.op("<=>", return_type=Float())(
                bindparam(None, other, type_=self.type)
            )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # Every user-document search filters on this.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(UUIDPk, Timestamps, Base):
    __tablename__ = "knowledge_documents"

    source: Mapped[str] = mapped_column(String(300), unique=True)  # path inside the KB folder
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(64))
    last_updated: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding)
