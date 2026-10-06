"""Application service between the API/CLI and the LangGraph graph.

Responsibilities:
  * customer identity: sign-in against the booking database, session tokens,
    and binding each conversation to the customer who started it;
  * running a conversation turn and the sensitive-action confirmation flow;
  * turning graph state into a clean response (text, sources, agent, pending action);
  * mapping failures to customer-safe errors while logging the real cause.
"""

import secrets
from contextlib import closing
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from customer_support_chat.app.core.errors import (
    AssistantBusyError,
    AssistantUnavailableError,
    ConversationBusyError,
    ConversationNotFoundError,
    CustomerNotIdentifiedError,
    NoPendingActionError,
    SupportError,
    TooManyLoginAttemptsError,
)
from customer_support_chat.app.core.logger import log_event, logger, mask_id
from customer_support_chat.app.core.settings import get_settings

# Customer-facing names for the assistants (never expose graph node names).
AGENT_LABELS = {
    "assistant": "Customer Support",
    "update_flight": "Flight Support",
    "book_car_rental": "Car Rental Support",
    "book_hotel": "Hotel Support",
    "book_excursion": "Trips & Excursions",
}

ACTION_TITLES = {
    "update_ticket_to_new_flight": "Change your flight",
    "cancel_ticket": "Cancel your flight ticket",
    "book_flight": "Book a new flight",
    "book_car_rental": "Book a car rental",
    "update_car_rental": "Change your car rental",
    "cancel_car_rental": "Cancel your car rental",
    "book_hotel": "Book a hotel",
    "update_hotel": "Change your hotel booking",
    "cancel_hotel": "Cancel your hotel booking",
    "book_excursion": "Book an excursion",
    "update_excursion": "Update your excursion",
    "cancel_excursion": "Cancel your excursion",
}

FALLBACK_REPLY = (
    "I'm sorry, I couldn't put together an answer to that. Could you rephrase your question?"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PendingAction:
    title: str
    details: list[dict]


@dataclass
class ChatResult:
    conversation_id: str
    response: str
    agent: str
    status: str = "success"  # "success" | "confirmation_required"
    sources: list[dict] = field(default_factory=list)
    pending_actions: list[PendingAction] = field(default_factory=list)


@dataclass
class Session:
    token: str
    passenger_id: str
    expires_at: float


@dataclass
class Conversation:
    owner: Optional[str]  # passenger id, or None for a guest conversation
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_active: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def message_text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type", "text") == "text" and part.get("text"):
                parts.append(part["text"])
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _humanize(key: str) -> str:
    return key.replace("_", " ").replace(" id", " ID").capitalize()


class ChatService:
    def __init__(self, graph_factory: Callable[[], Any], db_path: Optional[str] = None):
        self._graph_factory = graph_factory
        self._graph = None
        self._graph_lock = threading.Lock()
        self.settings = get_settings()
        self.db_path = db_path or self.settings.SQLITE_DB_PATH
        self._sessions: dict[str, Session] = {}
        self._conversations: dict[str, Conversation] = {}
        self._failed_logins: dict[str, list[float]] = {}
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------ graph

    @property
    def graph(self):
        with self._graph_lock:
            if self._graph is None:
                self._graph = self._graph_factory()
            return self._graph

    # --------------------------------------------------------------- identity

    def authenticate(self, passenger_id: str, booking_reference: str) -> Session:
        """Verify the customer owns a booking (passenger ID + booking reference or
        ticket number) and open a session."""
        passenger_id = (passenger_id or "").strip()
        reference = (booking_reference or "").strip().upper()
        if not passenger_id or not reference:
            raise CustomerNotIdentifiedError("Missing passenger ID or booking reference")

        window = self.settings.LOGIN_LOCKOUT_MINUTES * 60
        with self._state_lock:
            recent = [t for t in self._failed_logins.get(passenger_id, []) if t > time.time() - window]
            self._failed_logins[passenger_id] = recent
            if len(recent) >= self.settings.LOGIN_MAX_ATTEMPTS:
                log_event("auth.locked", passenger=mask_id(passenger_id))
                raise TooManyLoginAttemptsError("Too many failed sign-in attempts")

        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    "SELECT 1 FROM tickets WHERE passenger_id = ? AND (UPPER(book_ref) = ? OR ticket_no = ?) LIMIT 1",
                    (passenger_id, reference, reference),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.exception("Customer lookup failed")
            raise AssistantUnavailableError(str(exc)) from exc

        if row is None:
            with self._state_lock:
                self._failed_logins.setdefault(passenger_id, []).append(time.time())
            log_event("auth.failed", passenger=mask_id(passenger_id))
            raise CustomerNotIdentifiedError("Passenger ID and booking reference do not match")

        session = Session(
            token=secrets.token_urlsafe(32),
            passenger_id=passenger_id,
            expires_at=time.time() + self.settings.SESSION_TTL_MINUTES * 60,
        )
        with self._state_lock:
            self._failed_logins.pop(passenger_id, None)
            self._sessions[session.token] = session
        self._purge_expired()
        log_event("auth.success", passenger=mask_id(passenger_id))
        return session

    def get_session(self, token: Optional[str]) -> Optional[Session]:
        if not token:
            return None
        with self._state_lock:
            session = self._sessions.get(token)
            if session is None or session.expires_at < time.time():
                self._sessions.pop(token, None)
                raise CustomerNotIdentifiedError("Session expired or unknown")
            return session

    def logout(self, token: Optional[str]) -> None:
        with self._state_lock:
            self._sessions.pop(token or "", None)

    def _purge_expired(self) -> None:
        """Drop expired sessions and idle conversations, including their graph history."""
        now = time.time()
        idle_limit = now - self.settings.SESSION_TTL_MINUTES * 60
        with self._state_lock:
            for token in [t for t, s in self._sessions.items() if s.expires_at < now]:
                del self._sessions[token]
            lockout_start = now - self.settings.LOGIN_LOCKOUT_MINUTES * 60
            for pid in [p for p, times in self._failed_logins.items() if max(times, default=0) < lockout_start]:
                del self._failed_logins[pid]
            # Skip conversations that are still processing a message.
            stale = [
                cid for cid, conv in self._conversations.items()
                if conv.last_active < idle_limit and not conv.lock.locked()
            ]
            for cid in stale:
                del self._conversations[cid]
            graph = self._graph
        checkpointer = getattr(graph, "checkpointer", None)
        if checkpointer is not None:
            for cid in stale:
                try:
                    checkpointer.delete_thread(cid)
                except Exception:
                    logger.exception("Could not delete the history of an expired conversation")

    def _conversation(self, conversation_id: Optional[str], passenger_id: Optional[str], create: bool):
        if create and not conversation_id:
            # Guests never sign in, so also clean up when a new conversation starts.
            self._purge_expired()
        with self._state_lock:
            if not conversation_id:
                if not create:
                    raise ConversationNotFoundError("No conversation id supplied")
                conversation_id = str(uuid.uuid4())
                self._conversations[conversation_id] = Conversation(owner=passenger_id)
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                if not create:
                    raise ConversationNotFoundError(conversation_id)
                conversation = Conversation(owner=passenger_id)
                self._conversations[conversation_id] = conversation
            # A conversation is only ever accessible to the identity that started it.
            if conversation.owner != passenger_id:
                raise ConversationNotFoundError("Conversation belongs to a different customer")
            conversation.last_active = time.time()
            return conversation_id, conversation

    def _config(self, conversation_id: str, passenger_id: Optional[str]) -> dict:
        configurable = {"thread_id": conversation_id}
        if passenger_id:
            configurable["passenger_id"] = passenger_id
        return {"configurable": configurable, "recursion_limit": 40}

    # ------------------------------------------------------------------ turns

    def chat(self, message: str, conversation_id: Optional[str] = None,
             session: Optional[Session] = None) -> ChatResult:
        passenger_id = session.passenger_id if session else None
        conversation_id, conversation = self._conversation(conversation_id, passenger_id, create=True)
        config = self._config(conversation_id, passenger_id)

        with self._locked(conversation):
            log_event("chat.request", passenger=mask_id(passenger_id), chars=len(message))
            start = time.perf_counter()

            snapshot = self._run(lambda: self.graph.get_state(config))
            if snapshot.next:
                # A sensitive action is waiting, but the customer wrote something
                # instead of confirming: treat it as a refusal with their reasoning.
                graph_input = {
                    "messages": self._denial_messages(snapshot, message)
                }
            else:
                graph_input = {"messages": [HumanMessage(content=message)]}

            result = self._execute(graph_input, config, conversation_id, start)
        return result

    def confirm(self, conversation_id: str, approved: bool, reason: Optional[str] = None,
                session: Optional[Session] = None) -> ChatResult:
        passenger_id = session.passenger_id if session else None
        conversation_id, conversation = self._conversation(conversation_id, passenger_id, create=False)
        config = self._config(conversation_id, passenger_id)

        with self._locked(conversation):
            start = time.perf_counter()
            snapshot = self._run(lambda: self.graph.get_state(config))
            if not snapshot.next:
                raise NoPendingActionError(conversation_id)

            log_event("chat.confirmation", approved=approved, pending=list(snapshot.next))
            if approved:
                graph_input = None  # resume: execute the sensitive tool(s)
            else:
                graph_input = {
                    "messages": self._denial_messages(
                        snapshot, reason or "The customer declined the action."
                    )
                }
            return self._execute(graph_input, config, conversation_id, start)

    # -------------------------------------------------------------- internals

    def _locked(self, conversation: Conversation):
        service = self

        class _Guard:
            def __enter__(self_inner):
                if not conversation.lock.acquire(blocking=False):
                    raise ConversationBusyError("Conversation is already processing a message")

            def __exit__(self_inner, *exc):
                conversation.lock.release()
                return False

        return _Guard()

    @staticmethod
    def _denial_messages(snapshot, reason: str) -> list[ToolMessage]:
        last = snapshot.values["messages"][-1]
        return [
            ToolMessage(
                tool_call_id=tc["id"],
                content=(
                    f"API call denied by user. Reasoning: '{reason}'. "
                    "Continue assisting, accounting for the user's input."
                ),
            )
            for tc in getattr(last, "tool_calls", []) or []
        ]

    def _run(self, fn):
        try:
            return fn()
        except SupportError:
            raise
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if "RateLimit" in type(exc).__name__ or "RESOURCE_EXHAUSTED" in str(exc):
                logger.warning(f"LLM rate limit reached: {detail[:300]}")
                raise AssistantBusyError(detail) from exc
            logger.exception("Graph execution failed")
            raise AssistantUnavailableError(detail) from exc

    def _execute(self, graph_input, config, conversation_id: str, start: float) -> ChatResult:
        new_messages = []

        def run():
            for update in self.graph.stream(graph_input, config, stream_mode="updates"):
                for node, payload in update.items():
                    if node == "__interrupt__" or not isinstance(payload, dict):
                        continue
                    messages = payload.get("messages", [])
                    if not isinstance(messages, list):
                        messages = [messages]
                    new_messages.extend(messages)
                    tool_calls = [
                        tc["name"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls
                    ]
                    log_event("graph.node", node=node, tool_calls=tool_calls or None)
            return self.graph.get_state(config)

        snapshot = self._run(run)
        result = self._build_result(snapshot, new_messages, conversation_id)
        log_event(
            "chat.response",
            agent=result.agent,
            status=result.status,
            sources=len(result.sources),
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        return result

    def _build_result(self, snapshot, new_messages, conversation_id: str) -> ChatResult:
        values = snapshot.values or {}
        dialog_state = values.get("dialog_state") or []
        agent = AGENT_LABELS.get(dialog_state[-1] if dialog_state else "assistant", "Customer Support")

        # Sources: artifacts of knowledge-base lookups made during this turn.
        sources, seen = [], set()
        for msg in new_messages:
            if isinstance(msg, ToolMessage) and msg.name == "lookup_policy" and msg.artifact:
                for src in msg.artifact:
                    if src.get("chunk_id") not in seen:
                        seen.add(src.get("chunk_id"))
                        sources.append(src)

        ai_texts = [message_text(m) for m in new_messages if isinstance(m, AIMessage)]
        ai_texts = [t for t in ai_texts if t]
        response = ai_texts[-1] if ai_texts else ""

        if snapshot.next:
            last = values["messages"][-1]
            pending = [self.describe_action(tc) for tc in getattr(last, "tool_calls", []) or []]
            if not response:
                response = "Please review the action below and confirm whether I should go ahead."
            return ChatResult(
                conversation_id=conversation_id,
                response=response,
                agent=agent,
                status="confirmation_required",
                sources=sources,
                pending_actions=pending,
            )

        return ChatResult(
            conversation_id=conversation_id,
            response=response or FALLBACK_REPLY,
            agent=agent,
            sources=sources,
        )

    # --------------------------------------------------------- action preview

    def describe_action(self, tool_call: dict) -> PendingAction:
        """A customer-readable summary of a pending sensitive tool call."""
        name = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        details = []
        for key, value in args.items():
            if value in (None, ""):
                continue
            details.append({"label": _humanize(key), "value": str(value)})
            extra = self._lookup_entity(key, value)
            if extra:
                details.append(extra)
        title = ACTION_TITLES.get(name, "Confirm this action")
        return PendingAction(title=title, details=details)

    def _lookup_entity(self, key: str, value) -> Optional[dict]:
        queries = {
            "new_flight_id": ("New flight", "SELECT flight_no || ': ' || departure_airport || ' -> ' || arrival_airport || ', departs ' || substr(scheduled_departure, 1, 16) FROM flights WHERE flight_id = ?"),
            "flight_id": ("Flight", "SELECT flight_no || ': ' || departure_airport || ' -> ' || arrival_airport || ', departs ' || substr(scheduled_departure, 1, 16) FROM flights WHERE flight_id = ?"),
            "hotel_id": ("Hotel", "SELECT name || ', ' || location || ' (' || price_tier || ')' FROM hotels WHERE id = ?"),
            "rental_id": ("Car rental", "SELECT name || ', ' || location || ' (' || price_tier || ')' FROM car_rentals WHERE id = ?"),
            "recommendation_id": ("Excursion", "SELECT name || ', ' || location FROM trip_recommendations WHERE id = ?"),
        }
        if key not in queries:
            return None
        label, sql = queries[key]
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(sql, (value,)).fetchone()
        except sqlite3.Error:
            return None
        return {"label": label, "value": row[0]} if row and row[0] else None
