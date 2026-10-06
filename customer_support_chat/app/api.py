"""HTTP API for the customer support assistant.

Run with:  python -m customer_support_chat.app.api   (or: uvicorn customer_support_chat.app.api:app)

Endpoints
  POST /auth/login      passenger ID + booking reference -> session token
  POST /auth/logout
  POST /chat            send a message (works signed-in or as a guest)
  POST /chat/confirm    approve / decline a pending sensitive action
  GET  /health          readiness of LLM config, database and knowledge base
"""

import asyncio
import sqlite3
import uuid
from contextlib import asynccontextmanager, closing
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from customer_support_chat.app.core.errors import (
    AssistantTimeoutError,
    CustomerNotIdentifiedError,
    SupportError,
)
from customer_support_chat.app.core.logger import (
    conversation_id_var,
    log_event,
    logger,
    mask_id,
    request_id_var,
)
from customer_support_chat.app.core.settings import get_settings
from customer_support_chat.app.services.chat_service import ChatResult, ChatService, Session

settings = get_settings()

UUID_PATTERN = r"^[0-9a-fA-F-]{36}$"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    passenger_id: str = Field(min_length=3, max_length=40)
    booking_reference: str = Field(
        min_length=4, max_length=20, description="Booking reference (e.g. 06B046) or ticket number"
    )


class LoginResponse(BaseModel):
    session_token: str
    customer: str
    expires_in_minutes: int


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(default=None, pattern=UUID_PATTERN)
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be empty")
        return value.strip()


class ConfirmRequest(BaseModel):
    conversation_id: str = Field(pattern=UUID_PATTERN)
    approved: bool
    reason: Optional[str] = Field(default=None, max_length=500)


class Source(BaseModel):
    document_name: str
    section: str
    source: str
    chunk_id: str
    score: float


class ActionDetail(BaseModel):
    label: str
    value: str


class PendingActionOut(BaseModel):
    title: str
    details: list[ActionDetail]


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    sources: list[Source] = []
    agent: str
    status: Literal["success", "confirmation_required"]
    pending_actions: list[PendingActionOut] = []


def _to_response(result: ChatResult) -> ChatResponse:
    return ChatResponse(
        conversation_id=result.conversation_id,
        response=result.response,
        sources=[Source(**{k: s[k] for k in Source.model_fields}) for s in result.sources],
        agent=result.agent,
        status=result.status,
        pending_actions=[
            PendingActionOut(title=a.title, details=[ActionDetail(**d) for d in a.details])
            for a in result.pending_actions
        ],
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(service: Optional[ChatService] = None, warm_up: bool = True) -> FastAPI:
    if service is None:
        from customer_support_chat.app.graph import get_graph

        service = ChatService(graph_factory=get_graph)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if warm_up:
            # Load models and build the graph up-front so the first customer
            # doesn't pay for it. Failures are reported by /health, not fatal.
            def _warm():
                from customer_support_chat.app.services.rag import warm_up as rag_warm_up

                rag_warm_up()
                service.graph  # noqa: B018 - builds the graph (needs the LLM key)

            try:
                await asyncio.to_thread(_warm)
                logger.info("Warm-up complete")
            except Exception as exc:
                logger.error(f"Warm-up incomplete: {exc}")
        yield
        from vectorizer.app.vectordb.client import close_qdrant_client

        close_qdrant_client()

    app = FastAPI(title="Customer Support Assistant API", version="1.0.0", lifespan=lifespan)
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request_id_var.set(request_id)
        conversation_id_var.set("-")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ------------------------------------------------------------ errors

    def error_body(code: str, message: str) -> dict:
        return {"status": "error", "error": {"code": code, "message": message}}

    @app.exception_handler(SupportError)
    async def support_error_handler(request: Request, exc: SupportError):
        log_event("request.error", code=exc.code, detail=str(exc))
        return JSONResponse(error_body(exc.code, exc.user_message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
        return JSONResponse(
            error_body("invalid_request", f"Please check your input ({fields})."),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(error_body(SupportError.code, SupportError.user_message), status_code=500)

    # -------------------------------------------------------- dependencies

    def current_session(authorization: Optional[str] = Header(default=None)) -> Optional[Session]:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise CustomerNotIdentifiedError("Malformed Authorization header")
        return service.get_session(token)

    async def run_with_timeout(fn, *args, **kwargs):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs), timeout=settings.REQUEST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            raise AssistantTimeoutError("Request timed out") from exc

    # ------------------------------------------------------------- routes

    @app.post("/auth/login", response_model=LoginResponse)
    async def login(body: LoginRequest):
        session = await asyncio.to_thread(
            service.authenticate, body.passenger_id, body.booking_reference
        )
        return LoginResponse(
            session_token=session.token,
            customer=mask_id(session.passenger_id),
            expires_in_minutes=settings.SESSION_TTL_MINUTES,
        )

    @app.post("/auth/logout")
    async def logout(authorization: Optional[str] = Header(default=None)):
        service.logout((authorization or "").partition(" ")[2])
        return {"status": "success"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, session: Optional[Session] = Depends(current_session)):
        if body.conversation_id:
            conversation_id_var.set(body.conversation_id)
        result = await run_with_timeout(
            service.chat, body.message, conversation_id=body.conversation_id, session=session
        )
        conversation_id_var.set(result.conversation_id)
        return _to_response(result)

    @app.post("/chat/confirm", response_model=ChatResponse)
    async def confirm(body: ConfirmRequest, session: Optional[Session] = Depends(current_session)):
        conversation_id_var.set(body.conversation_id)
        result = await run_with_timeout(
            service.confirm, body.conversation_id, body.approved, body.reason, session=session
        )
        return _to_response(result)

    @app.get("/health")
    async def health():
        checks = {"llm_configured": bool(settings.GEMINI_API_KEY)}
        try:
            with closing(sqlite3.connect(f"file:{service.db_path}?mode=ro", uri=True)) as conn:
                conn.execute("SELECT 1 FROM tickets LIMIT 1")
            checks["database"] = True
        except sqlite3.Error:
            checks["database"] = False
        try:
            from customer_support_chat.app.services.rag import get_retriever

            checks["knowledge_base"] = await asyncio.to_thread(
                get_retriever().vectordb.collection_ready
            )
        except Exception:
            checks["knowledge_base"] = False
        healthy = all(checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status_code=200 if healthy else 503,
        )

    return app


# Cheap to create: the graph, models and vector store are only loaded at startup / first use.
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "customer_support_chat.app.api:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level="info",
    )
