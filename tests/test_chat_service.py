"""ChatService housekeeping: sign-in throttling and cleanup of idle conversations."""

import time

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from customer_support_chat.app.core.errors import (
    CustomerNotIdentifiedError,
    TooManyLoginAttemptsError,
)
from customer_support_chat.app.services import chat_service as chat_service_module
from customer_support_chat.app.services.chat_service import ChatService
from tests.conftest import BOOK_REF, PASSENGER


def _echo_graph():
    builder = StateGraph(MessagesState)
    builder.add_node("echo", lambda state: {"messages": [("ai", "hi")]})
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    return builder.compile(checkpointer=MemorySaver())


@pytest.fixture
def plain_service(db):
    return ChatService(graph_factory=_echo_graph, db_path=db)


def _fail(service, times):
    for _ in range(times):
        with pytest.raises(CustomerNotIdentifiedError):
            service.authenticate(PASSENGER, "WRONG1")


# ------------------------------------------------------------ sign-in throttle


def test_login_locked_after_repeated_failures(plain_service):
    _fail(plain_service, plain_service.settings.LOGIN_MAX_ATTEMPTS)
    # Even the correct reference is refused while locked.
    with pytest.raises(TooManyLoginAttemptsError):
        plain_service.authenticate(PASSENGER, BOOK_REF)


def test_lockout_is_per_passenger(plain_service):
    _fail(plain_service, plain_service.settings.LOGIN_MAX_ATTEMPTS)
    with pytest.raises(CustomerNotIdentifiedError):
        plain_service.authenticate("9999 000000", "WRONG1")


def test_successful_login_resets_failures(plain_service):
    _fail(plain_service, plain_service.settings.LOGIN_MAX_ATTEMPTS - 1)
    plain_service.authenticate(PASSENGER, BOOK_REF)
    _fail(plain_service, plain_service.settings.LOGIN_MAX_ATTEMPTS - 1)
    assert plain_service.authenticate(PASSENGER, BOOK_REF).passenger_id == PASSENGER


def test_lockout_expires(plain_service, monkeypatch):
    _fail(plain_service, plain_service.settings.LOGIN_MAX_ATTEMPTS)
    later = time.time() + plain_service.settings.LOGIN_LOCKOUT_MINUTES * 60 + 1
    monkeypatch.setattr(chat_service_module.time, "time", lambda: later)
    assert plain_service.authenticate(PASSENGER, BOOK_REF).passenger_id == PASSENGER


# ------------------------------------------------------- conversation cleanup


def _idle_conversation(service):
    cid, conversation = service._conversation(None, None, create=True)
    config = service._config(cid, None)
    service.graph.invoke({"messages": [("user", "hello")]}, config)
    conversation.last_active = time.time() - service.settings.SESSION_TTL_MINUTES * 60 - 1
    return cid, conversation, config


def test_idle_conversation_history_is_deleted(plain_service):
    cid, _, config = _idle_conversation(plain_service)
    assert plain_service.graph.checkpointer.get_tuple(config) is not None

    plain_service._conversation(None, None, create=True)  # a new guest conversation triggers cleanup

    assert cid not in plain_service._conversations
    assert plain_service.graph.checkpointer.get_tuple(config) is None


def test_busy_conversation_is_not_purged(plain_service):
    cid, conversation, config = _idle_conversation(plain_service)
    with conversation.lock:
        plain_service._conversation(None, None, create=True)
    assert cid in plain_service._conversations
    assert plain_service.graph.checkpointer.get_tuple(config) is not None
