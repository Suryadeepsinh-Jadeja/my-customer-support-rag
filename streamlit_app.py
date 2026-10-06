"""
Streamlit chat UI for the customer support assistant.

The UI is a thin client of the backend API (customer_support_chat/app/api.py):

User -> Streamlit -> POST /chat -> LangGraph (primary + specialist assistants,
RAG, tools) -> response with sources / pending confirmation -> Streamlit

Run the API first:   python -m customer_support_chat.app.api
Then:                streamlit run streamlit_app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

# ============================================================
# PATH / ENVIRONMENT
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
DEMO_PASSENGER_ID = os.getenv("DEMO_PASSENGER_ID", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120")) + 10
GRAPH_IMAGE = REPO_ROOT / "graphs" / "multi-agent-rag-system-graph.png"

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Swiss Airlines Customer Support",
    page_icon="✈️",
    layout="wide",
)

# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "messages": [],          # chat history: {role, content, agent?, sources?, actions?}
    "conversation_id": None,
    "token": None,
    "customer": None,
    "pending": None,         # last response awaiting confirmation
    "queued": None,          # demo question waiting to be sent
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


# ============================================================
# API CLIENT
# ============================================================


class ApiError(Exception):
    pass


def api_post(path: str, payload: dict) -> dict:
    headers = {}
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        response = requests.post(f"{API_URL}{path}", json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        raise ApiError("The assistant is taking too long to respond. Please try again.")
    except requests.ConnectionError:
        raise ApiError("We can't reach the support service right now. Please try again in a moment.")

    try:
        body = response.json()
    except ValueError:
        raise ApiError("Unexpected response from the support service. Please try again.")

    if response.status_code >= 400:
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if error.get("code") in {"not_authenticated", "conversation_not_found"} and st.session_state.token:
            sign_out(local_only=True)
        raise ApiError(error.get("message", "Something went wrong. Please try again."))
    return body


@st.cache_data(ttl=15, show_spinner=False)
def service_health() -> dict | None:
    try:
        return requests.get(f"{API_URL}/health", timeout=5).json()
    except Exception:
        return None


def sign_out(local_only: bool = False):
    if not local_only and st.session_state.token:
        try:
            api_post("/auth/logout", {})
        except ApiError:
            pass
    for key in ("token", "customer", "conversation_id", "pending"):
        st.session_state[key] = None
    st.session_state.messages = []


def new_conversation():
    st.session_state.messages = []
    st.session_state.conversation_id = None
    st.session_state.pending = None


def record_response(body: dict):
    st.session_state.conversation_id = body["conversation_id"]
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": body["response"],
            "agent": body.get("agent"),
            "sources": body.get("sources", []),
            "actions": body.get("pending_actions", []),
        }
    )
    st.session_state.pending = body if body.get("status") == "confirmation_required" else None


def send_message(text: str):
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.markdown(text)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                body = api_post("/chat", {"conversation_id": st.session_state.conversation_id, "message": text})
            except ApiError as e:
                st.session_state.messages.append({"role": "error", "content": str(e)})
                return
    record_response(body)


def send_confirmation(approved: bool, reason: str | None = None):
    pending = st.session_state.pending
    st.session_state.pending = None
    st.session_state.messages.append(
        {"role": "user", "content": "✅ Confirmed" if approved else f"❌ Declined{f': {reason}' if reason else ''}"}
    )
    try:
        with st.spinner("Processing your request..."):
            body = api_post(
                "/chat/confirm",
                {"conversation_id": pending["conversation_id"], "approved": approved, "reason": reason or None},
            )
    except ApiError as e:
        st.session_state.messages.append({"role": "error", "content": str(e)})
        return
    record_response(body)


# ============================================================
# RENDERING
# ============================================================


def render_sources(sources: list[dict]):
    if not sources:
        return
    with st.expander(f"📚 Sources ({len(sources)})"):
        for src in sources:
            st.markdown(f"- **{src['document_name']}** — {src['section']}  \n  `{src['source']}`")


def render_actions(actions: list[dict]):
    for action in actions:
        with st.container(border=True):
            st.markdown(f"**🔒 {action['title']}**")
            for detail in action["details"]:
                st.markdown(f"- {detail['label']}: **{detail['value']}**")


def render_message(message: dict):
    role = message["role"]
    if role == "error":
        st.error(message["content"], icon="⚠️")
        return
    with st.chat_message(role):
        if role == "assistant" and message.get("agent"):
            st.caption(message["agent"])
        st.markdown(message["content"])
        if role == "assistant":
            render_actions(message.get("actions", []))
            render_sources(message.get("sources", []))


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title("✈️ My Account")

    if st.session_state.token:
        st.success(f"Signed in as passenger {st.session_state.customer}", icon="👤")
        if st.button("Sign out", use_container_width=True):
            sign_out()
            st.rerun()
    else:
        st.caption("Sign in to view and manage your bookings. Policy questions work without signing in.")
        with st.form("sign_in"):
            passenger_id = st.text_input("Passenger ID", value=DEMO_PASSENGER_ID, placeholder="e.g. 8149 604011")
            reference = st.text_input("Booking reference or ticket number", placeholder="e.g. 06B046")
            if st.form_submit_button("Sign in", use_container_width=True):
                try:
                    body = api_post("/auth/login", {"passenger_id": passenger_id, "booking_reference": reference})
                except ApiError as e:
                    st.error(str(e))
                else:
                    new_conversation()
                    st.session_state.token = body["session_token"]
                    st.session_state.customer = body["customer"]
                    st.rerun()

    st.divider()

    if st.button("🧹 New conversation", use_container_width=True):
        new_conversation()
        st.rerun()

    # --------------------------------------------------------
    # SERVICE STATUS
    # --------------------------------------------------------

    st.subheader("Service status")
    health = service_health()
    if health is None:
        st.error("Support service offline", icon="🔴")
    elif health.get("status") == "ok":
        st.success("All systems operational", icon="🟢")
    else:
        st.warning("Some services are degraded", icon="🟠")
        labels = {"llm_configured": "Assistant", "database": "Booking system", "knowledge_base": "Policy library"}
        for check, ok in health.get("checks", {}).items():
            st.caption(f"{'✅' if ok else '❌'} {labels.get(check, check)}")

    # --------------------------------------------------------
    # ABOUT / ARCHITECTURE
    # --------------------------------------------------------

    with st.expander("ℹ️ How this assistant works"):
        st.markdown(
            """
1. **Primary assistant** understands your request.
2. Policy questions are answered from the **official policy library** (with sources).
3. Booking requests are handled by a **specialist** for flights, hotels, car rentals or excursions.
4. Any booking, change or cancellation is shown to you first and only runs after **you confirm**.
"""
        )
        if GRAPH_IMAGE.exists():
            st.image(str(GRAPH_IMAGE), use_container_width=True)


# ============================================================
# MAIN PAGE
# ============================================================

st.title("✈️ Swiss Airlines Customer Support")
st.caption("Ask about your bookings, our policies, hotels, car rentals and excursions.")

# ============================================================
# SUGGESTED QUESTIONS
# ============================================================

if not st.session_state.messages:
    st.subheader("How can we help?")
    demo_questions = [
        "What is the baggage policy?",
        "Show me my flight information.",
        "Can I cancel my flight, and what refund will I get?",
        "I want to change my flight.",
        "I want to book a hotel.",
        "I need a rental car.",
        "Recommend an excursion for my trip.",
        "What documents do I need to travel?",
    ]
    cols = st.columns(2)
    for i, question in enumerate(demo_questions):
        if cols[i % 2].button(question, use_container_width=True, key=f"demo_{i}"):
            st.session_state.queued = question
            st.rerun()

# ============================================================
# CHAT HISTORY
# ============================================================

for message in st.session_state.messages:
    render_message(message)

# ============================================================
# CONFIRMATION
# ============================================================

if st.session_state.pending:
    with st.container(border=True):
        st.markdown("**Do you want me to go ahead with this?**")
        reason = st.text_input("Optional: tell us what you'd like instead", key="decline_reason")
        confirm_col, decline_col = st.columns(2)
        if confirm_col.button("✅ Confirm", type="primary", use_container_width=True):
            send_confirmation(True)
            st.rerun()
        if decline_col.button("❌ Decline", use_container_width=True):
            send_confirmation(False, reason)
            st.rerun()

# ============================================================
# CHAT INPUT
# ============================================================

placeholder = (
    "Or reply to change the request..."
    if st.session_state.pending
    else "Ask about flights, policies, hotels, car rentals or excursions..."
)
query = st.chat_input(placeholder)

if st.session_state.queued and not query:
    query, st.session_state.queued = st.session_state.queued, None

if query:
    send_message(query)
    st.rerun()
