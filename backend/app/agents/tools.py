"""Tools the assistant can call, and the code that runs them.

The model only ever chooses a tool and its arguments. Who the user is always comes from
`ToolContext` (the authenticated request), never from model arguments, and argument
models forbid unknown keys, so a `user_id` slipped in by the model is rejected.

Every call is logged as a `ToolExecution` with the argument keys only, never values.
Results are returned to the model as untrusted data.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import document_checks
from app.agents.document_checks import DocFields
from app.core.errors import AppError
from app.core.logging import mask
from app.db.models import Document, DocumentType, ExtractedEntity, ToolExecution, User
from app.providers import ProviderError
from app.rag import retrieval
from app.services.llm_service import ToolCall, ToolSpec

logger = logging.getLogger("travel.tools")


@dataclass
class ToolContext:
    session: AsyncSession
    user: User
    conversation_id: uuid.UUID | None = None
    # Citations and UI cards (offers, bookings, confirmations) from one assistant turn.
    sources: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)

    def cite(self, source: dict[str, Any]) -> None:
        if source not in self.sources:
            self.sources.append(source)


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[ToolArgs]
    handler: Handler
    requires_confirmation: bool = False
    requires_payment: bool = False
    reversible: bool = True

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.args.model_json_schema())


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, args: type[ToolArgs] = ToolArgs, *,
         requires_confirmation: bool = False, requires_payment: bool = False,
         reversible: bool = True):
    def register(handler: Handler) -> Handler:
        TOOLS[name] = Tool(name, description, args, handler, requires_confirmation,
                           requires_payment, reversible)
        return handler
    return register


async def execute(ctx: ToolContext, call: ToolCall, allowed: list[str]) -> dict[str, Any]:
    """Run one tool call from the model. Errors become results the model can explain."""
    start = time.perf_counter()
    error: str | None = None
    tool_ = TOOLS.get(call.name) if call.name in allowed else None
    try:
        if tool_ is None:
            error = "unknown_tool"
            return {"error": f"There is no tool named {call.name!r}."}
        try:
            args = tool_.args.model_validate(call.args)
        except ValidationError:
            error = "invalid_arguments"
            return {"error": "The arguments were invalid. Check the tool's parameters."}
        try:
            return await tool_.handler(ctx, args)
        except (AppError, ProviderError) as exc:  # expected refusals, safe to show
            error = getattr(exc, "code", "refused")
            return {"error": exc.message}
        except Exception:
            logger.exception("tool failed", extra={"tool": call.name})
            error = "tool_failed"
            return {"error": "The tool failed. Tell the user it couldn't be checked right now."}
    finally:
        ctx.session.add(ToolExecution(
            user_id=ctx.user.id, conversation_id=ctx.conversation_id, tool=call.name[:64],
            arg_keys=sorted(call.args)[:20], status="error" if error else "success",
            latency_ms=round((time.perf_counter() - start) * 1000), error_code=error,
        ))


# ------------------------------------------------------------------- phase 4 tools


class QueryArgs(ToolArgs):
    query: str = Field(min_length=2, max_length=300,
                       description="What to look for, in natural language")


@tool("search_user_documents",
      "Full-text search over the travel documents the user uploaded (tickets, passports, "
      "hotel bookings, ...). Returns matching passages with document name and page.",
      QueryArgs)
async def search_user_documents(ctx: ToolContext, args: QueryArgs) -> dict[str, Any]:
    hits = await retrieval.search_user_documents(ctx.session, ctx.user.id, args.query)
    for h in hits:
        ctx.cite({"type": "document", "title": h.title, "document_id": h.document_id,
                  "page": h.page})
    return {"results": [
        {"document": h.title, "document_type": h.document_type, "page": h.page, "text": h.text}
        for h in hits
    ]}


class FieldArgs(ToolArgs):
    document_type: DocumentType | None = Field(
        default=None, description="Only documents of this type")
    field: str | None = Field(
        default=None, max_length=64,
        description="Only documents that have this field, e.g. flight_number, "
                    "arrival_time, baggage_allowance, passport_number, expiry_date, "
                    "check_in, confirmation_number")


async def _load_fields(ctx: ToolContext, document_type: DocumentType | None = None,
                       field: str | None = None) -> dict[uuid.UUID, dict[str, Any]]:
    """The user's extracted fields grouped by document, newest document first."""
    query = (select(ExtractedEntity, Document.filename, Document.document_type)
             .join(Document, Document.id == ExtractedEntity.document_id)
             .where(ExtractedEntity.user_id == ctx.user.id, Document.user_id == ctx.user.id)
             .order_by(Document.created_at.desc(), ExtractedEntity.group_index,
                       ExtractedEntity.id))
    if document_type:
        query = query.where(Document.document_type == document_type)
    if field:
        # Narrow to documents that have the field, but return all their fields so the
        # value comes with its context (which flight, which date).
        name = field.strip().lower().replace(" ", "_")
        query = query.where(ExtractedEntity.document_id.in_(
            select(ExtractedEntity.document_id).where(ExtractedEntity.user_id == ctx.user.id,
                                                      ExtractedEntity.field == name)))

    documents: dict[uuid.UUID, dict[str, Any]] = {}
    for row in (await ctx.session.execute(query.limit(500))).all():
        e = row.ExtractedEntity
        doc = documents.setdefault(e.document_id, {
            "document": row.filename,
            "document_type": row.document_type.value if row.document_type else None,
            "fields": [], "pages": set(),
        })
        doc["fields"].append({"field": e.field, "value": e.value, "segment": e.group_index + 1,
                              "page": e.page, "confidence": e.confidence})
        if e.page:
            doc["pages"].add(e.page)
    return documents


def _cite_document(ctx: ToolContext, document_id: uuid.UUID, doc: dict[str, Any]) -> None:
    pages = sorted(doc["pages"])
    ctx.cite({"type": "document", "title": doc["document"], "document_id": str(document_id),
              "page": pages[0] if pages else None})


@tool("get_document_fields",
      "Structured fields extracted from the user's documents (flight number, times, "
      "seat, passport number and expiry, hotel dates, ...), grouped by document, with the "
      "page each value was found on. Multi-flight tickets number their flights by `segment`.",
      FieldArgs)
async def get_document_fields(ctx: ToolContext, args: FieldArgs) -> dict[str, Any]:
    documents = await _load_fields(ctx, args.document_type, args.field)
    for document_id, doc in documents.items():
        _cite_document(ctx, document_id, doc)
    return {"documents": [{k: v for k, v in d.items() if k != "pages"}
                          for d in documents.values()]}


@tool("search_policies",
      "Search the travel company's policy knowledge base (baggage, changes, cancellations, "
      "refunds, check-in, hotels, car rental, travel documents, ...).",
      QueryArgs)
async def search_policies(ctx: ToolContext, args: QueryArgs) -> dict[str, Any]:
    hits = await retrieval.search_knowledge(ctx.session, args.query, limit=3)
    for h in hits:
        ctx.cite({"type": "policy", "title": h.title, "section": h.section})
    return {"results": [{"policy": h.title, "section": h.section, "text": h.text}
                        for h in hits]}


@tool("get_user_profile",
      "The user's profile and travel preferences: name, nationality, home airport, "
      "preferred airports, airlines, cabin, seat and meal, frequent-flyer programmes.")
async def get_user_profile(ctx: ToolContext, args: ToolArgs) -> dict[str, Any]:
    profile, prefs = ctx.user.profile, ctx.user.preferences
    result: dict[str, Any] = {}
    if profile:
        result |= {"full_name": profile.full_name, "nationality": profile.nationality,
                   "home_airport": profile.home_airport}
    if prefs:
        result |= {
            "preferred_airports": prefs.preferred_airports,
            "preferred_airlines": prefs.preferred_airlines,
            "preferred_cabin": prefs.preferred_cabin.value if prefs.preferred_cabin else None,
            "seat_preference": prefs.seat_preference,
            "meal_preference": prefs.meal_preference,
            "frequent_flyer_programs": [
                {"airline": p.get("airline"), "number": mask(p.get("number"))}
                for p in prefs.frequent_flyer_programs or []
            ],
            "notes": prefs.notes,
        }
    return result


@tool("list_documents",
      "List the travel documents the user has uploaded: file name, detected type, "
      "processing status and upload date.")
async def list_documents(ctx: ToolContext, args: ToolArgs) -> dict[str, Any]:
    rows = (await ctx.session.execute(
        select(Document).where(Document.user_id == ctx.user.id)
        .order_by(Document.created_at.desc()).limit(100)
    )).scalars()
    return {"documents": [
        {"document": d.filename,
         "document_type": d.document_type.value if d.document_type else None,
         "status": d.status.value, "uploaded": d.created_at.date().isoformat(),
         "pages": d.page_count}
        for d in rows
    ]}


@tool("check_travel_documents",
      "Check the user's documents against each other: passenger name vs passport name, "
      "passport validity (expired, or under 6 months at a travel date), hotel dates that "
      "don't match the flights, and two tickets departing on the same day.")
async def check_travel_documents(ctx: ToolContext, args: ToolArgs) -> dict[str, Any]:
    documents = await _load_fields(ctx)
    docs = [DocFields(d["document"], d["document_type"],
                      [(f["field"], f["value"], f["segment"]) for f in d["fields"]])
            for d in documents.values()]
    issues = document_checks.check(docs, date.today())
    involved = {name for issue in issues for name in issue.documents}
    for document_id, doc in documents.items():
        if doc["document"] in involved:
            _cite_document(ctx, document_id, doc)
    return {
        "documents_checked": [{"document": d.filename, "document_type": d.document_type}
                              for d in docs],
        "issues": [{"kind": i.kind, "severity": i.severity, "message": i.message}
                   for i in issues],
    }
