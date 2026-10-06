import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event, request_id_var
from app.db.models import AuditLog


async def record(
    session: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    status: str = "success",
    actor: str = "user",
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the caller's transaction (committed together with the change)."""
    session.add(
        AuditLog(
            user_id=user_id,
            actor=actor,
            action=action,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id_var.get(),
            ip_address=ip_address,
            details=details or {},
        )
    )
    log_event(f"audit.{action}", status=status, audit_user=str(user_id) if user_id else None)
