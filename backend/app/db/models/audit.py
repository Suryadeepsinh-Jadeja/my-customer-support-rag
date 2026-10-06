import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk, utcnow


class AuditLog(UUIDPk, Base):
    """Append-only record of security-relevant and state-changing actions.

    `details` must never contain raw PII (passport numbers, passwords, full documents).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_user_created", "user_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
    # Kept (as NULL) when the user is deleted so the trail survives account deletion.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor: Mapped[str] = mapped_column(String(16), default="user")  # user | admin | system
    action: Mapped[str] = mapped_column(String(64), index=True)  # e.g. auth.login
    status: Mapped[str] = mapped_column(String(16), default="success")  # success | failure
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
