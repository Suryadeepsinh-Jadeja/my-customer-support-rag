"""Admin overview. Operational data only: no document text, filenames, traveller names or
unmasked booking references."""

import uuid
from typing import Any

from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class AdminUser(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: UtcDatetime
    last_login_at: UtcDatetime | None
    documents: int
    bookings: int
    conversations: int


class AdminDocument(BaseModel):
    id: uuid.UUID
    owner: str  # masked email
    document_type: str | None
    status: str
    error_code: str | None
    created_at: UtcDatetime


class AdminBooking(BaseModel):
    id: uuid.UUID
    owner: str  # masked email
    kind: str
    provider: str
    status: str
    reference: str | None  # masked
    total_amount: float
    currency: str
    error_code: str | None
    created_at: UtcDatetime


class AdminToolStat(BaseModel):
    tool: str
    calls: int
    errors: int
    avg_latency_ms: int


class AdminToolError(BaseModel):
    tool: str
    error_code: str | None
    latency_ms: int
    created_at: UtcDatetime


class AdminJobError(BaseModel):
    id: uuid.UUID
    kind: str
    attempts: int
    last_error: str | None
    updated_at: UtcDatetime


class AdminOverview(BaseModel):
    ready: dict[str, Any]
    counts: dict[str, int]
    users: list[AdminUser]
    documents_by_status: dict[str, int]
    failed_documents: list[AdminDocument]
    bookings: list[AdminBooking]
    tools: list[AdminToolStat]
    tool_errors: list[AdminToolError]
    failed_jobs: list[AdminJobError]
