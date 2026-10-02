"""
Streamlit front-end for the Multi-Agent RAG Customer Support backend.

Run from the repository root:

    streamlit run streamlit_app.py

The backend (``customer_support_chat``) is imported, never re-implemented. This file
only handles configuration, streaming the LangGraph run, visualising each agent
step, and the human-in-the-loop approval flow for sensitive tools.

Why the backend is imported lazily: ``core/settings.py`` and ``assistant_base.py``
read ``OPENAI_API_KEY`` / ``QDRANT_URL`` at *import time* and build the shared
``ChatOpenAI`` instance as a module global. To use a key typed into the sidebar we
set the environment first, then import. Each distinct configuration gets its own
freshly imported graph (and its own MemorySaver), cached with ``st.cache_resource``.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage

# --------------------------------------------------------------------------------------
# Paths & environment
# --------------------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
# The backend uses paths relative to the repo root (./customer_support_chat/data/...).
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env as defaults; never overrides variables already set in the shell.
load_dotenv(REPO_ROOT / ".env")

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
APP_TITLE = "Swiss Airlines Support"
USER_AVATAR = "🧑"
ASSISTANT_AVATAR = "🛎️"
DEFAULT_PASSENGER_ID = "5102 899977"  # same default as customer_support_chat/app/main.py
GRAPH_IMAGE = REPO_ROOT / "graphs" / "multi-agent-rag-system-graph.png"

# Label -> model name. ``None`` keeps whatever assistant_base.py configures (gpt-4).
MODEL_OPTIONS: dict[str, str | None] = {
    "Backend default (gpt-4)": None,
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
}

EXPECTED_COLLECTIONS = (
    "flights_collection",
    "hotels_collection",
    "car_rentals_collection",
    "excursions_collection",
    "faq_collection",
)

# Agent node name (as registered in graph.py) -> (display label, icon)
AGENTS: dict[str, tuple[str, str]] = {
    "primary_assistant": ("Primary Assistant", "🧭"),
    "update_flight": ("Flight Assistant", "✈️"),
    "book_car_rental": ("Car Rental Assistant", "🚗"),
    "book_hotel": ("Hotel Assistant", "🏨"),
    "book_excursion": ("Excursion Assistant", "🗺️"),
}

SUGGESTED_PROMPTS = (
    "What flights do I currently have booked?",
    "Can I move my flight to later this week?",
    "Find me a hotel in Basel for my trip",
    "What's the policy on changing a ticket?",
)

TOOL_RESULT_PREVIEW_CHARS = 700

# Same wording the CLI (main.py) uses when the user rejects an action.
DENIAL_TEMPLATE = (
    "API call denied by user. Reasoning: '{reason}'. "
    "Continue assisting, accounting for the user's input."
)

log = logging.getLogger("streamlit_app")

# --------------------------------------------------------------------------------------
# Backend loading
# --------------------------------------------------------------------------------------
_IMPORT_LOCK = threading.Lock()
_BACKEND_PACKAGES = ("customer_support_chat", "vectorizer")


@dataclass(frozen=True)
class Backend:
    """Handles to the imported backend objects the UI needs."""

    graph: Any                       # compiled multi_agentic_graph
    delegation_tools: dict[str, str]  # routing tool name -> target agent node
    escalate_tool: str               # CompleteOrEscalate tool name
    sensitive_tools: frozenset[str]  # tool names that trigger an approval interrupt
    interrupt_nodes: frozenset[str]  # graph nodes compiled with interrupt_before
    model_name: str


def _purge_backend_modules() -> None:
    """Drop cached backend modules so the next import re-reads the environment."""
    for name in list(sys.modules):
        if name.split(".")[0] in _BACKEND_PACKAGES:
            del sys.modules[name]
    # Backend loggers attach a handler on every import; avoid duplicate log lines.
    for logger_name in ("customer_support_chat", "vectorizer.app.core.logger"):
        logging.getLogger(logger_name).handlers.clear()


@st.cache_resource(show_spinner=False, max_entries=8)
def load_backend(
    key_fingerprint: str,
    qdrant_url: str,
    model: str | None,
    temperature: float,
    _api_key: str,
) -> Backend:
    """Import the backend for one configuration.

    ``key_fingerprint`` is part of the cache key; ``_api_key`` (underscore = not hashed
    by Streamlit) carries the secret itself.
    """
    with _IMPORT_LOCK:
        previous_env = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "QDRANT_URL")}
        os.environ["OPENAI_API_KEY"] = _api_key
        os.environ["QDRANT_URL"] = qdrant_url
        try:
            _purge_backend_modules()
            utils = importlib.import_module("customer_support_chat.app.services.utils")
            utils.download_and_prepare_db()  # no-op if the SQLite DB already exists

            graph_mod = importlib.import_module("customer_support_chat.app.graph")
            base = importlib.import_module(
                "customer_support_chat.app.services.assistants.assistant_base"
            )
            primary = importlib.import_module(
                "customer_support_chat.app.services.assistants.primary_assistant"
            )
            assistants = importlib.import_module(
                "customer_support_chat.app.services.assistants"
            )

            # Every assistant runnable is ``prompt | llm.bind_tools(...)`` around the one
            # shared ``llm`` object, so adjusting it here applies to all agents. Because
            # this instance was just imported for this configuration, no other
            # configuration is affected.
            if model:
                base.llm.model_name = model
            base.llm.temperature = temperature

            sensitive = (
                assistants.update_flight_sensitive_tools
                + assistants.book_car_rental_sensitive_tools
                + assistants.book_hotel_sensitive_tools
                + assistants.book_excursion_sensitive_tools
            )
            return Backend(
                graph=graph_mod.multi_agentic_graph,
                delegation_tools={
                    primary.ToFlightBookingAssistant.__name__: "update_flight",
                    primary.ToBookCarRental.__name__: "book_car_rental",
                    primary.ToHotelBookingAssistant.__name__: "book_hotel",
                    primary.ToBookExcursion.__name__: "book_excursion",
                },
                escalate_tool=base.CompleteOrEscalate.__name__,
                sensitive_tools=frozenset(t.name for t in sensitive),
                interrupt_nodes=frozenset(graph_mod.interrupt_nodes),
                model_name=base.llm.model_name,
            )
        finally:
            # The key now lives inside the imported clients; don't leave it in the
            # process environment where another session's import could pick it up.
            for k, v in previous_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


@st.cache_data(ttl=20, show_spinner=False)
def check_qdrant(url: str) -> tuple[bool, str, dict[str, int]]:
    """Return (reachable, error, {collection: point_count}) for the expected collections."""
    from qdrant_client import QdrantClient

    try:
        client = QdrantClient(url=url, timeout=3)
        existing = {c.name for c in client.get_collections().collections}
        counts = {
            name: client.count(collection_name=name, exact=False).count
            for name in EXPECTED_COLLECTIONS
            if name in existing
        }
        return True, "", counts
    except Exception as exc:  # noqa: BLE001 - surface any connection problem
        return False, str(exc), {}


def configure_langsmith(api_key: str, project: str) -> None:
    """Enable LangSmith tracing if a key is available, otherwise disable it.

    .dev.env ships with LANGCHAIN_TRACING_V2=true and an empty key, which floods the
    console with 401 errors; turning tracing off in that case keeps logs readable.
    """
    if api_key:
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if project:
            os.environ["LANGCHAIN_PROJECT"] = project
    elif not os.environ.get("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "false"


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:16]


def secret_from_streamlit(name: str) -> str:
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:  # noqa: BLE001 - no secrets.toml is fine
        return ""


# --------------------------------------------------------------------------------------
# Turning graph updates into displayable steps
# --------------------------------------------------------------------------------------
def agent_for_node(node: str) -> str:
    """Map any graph node to the agent it belongs to (e.g. book_hotel_safe_tools -> book_hotel)."""
    if node.startswith("enter_"):
        return node[len("enter_"):]
    for suffix in ("_safe_tools", "_sensitive_tools", "_tools"):
        if node.endswith(suffix):
            return node[: -len(suffix)]
    return node


def agent_label(agent: str, with_icon: bool = True) -> str:
    label, icon = AGENTS.get(agent, (agent.replace("_", " ").title(), "🤖"))
    return f"{icon} {label}" if with_icon else label


def message_text(content: Any) -> str:
    """Flatten LangChain message content (str or list of content blocks) to text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class TurnRecorder:
    """Consumes ``stream_mode="updates"`` events and produces serialisable steps.

    Steps are plain dicts so they can live in ``st.session_state`` and be re-rendered
    on every rerun (and exported as JSON).
    """

    def __init__(self, backend: Backend):
        self.backend = backend
        self.steps: list[dict] = []
        self.agents: list[str] = []
        self.final_text: str | None = None
        self.last_thought: str | None = None
        self._tool_names: dict[str, str] = {}

    def _add(self, step: dict) -> dict:
        self.steps.append(step)
        return step

    def _saw_agent(self, agent: str) -> None:
        if not self.agents or self.agents[-1] != agent:
            self.agents.append(agent)

    def consume(self, node: str, update: dict) -> list[dict]:
        new: list[dict] = []
        if node == "fetch_user_info":
            info = update.get("user_info", "") or ""
            new.append(self._add({
                "kind": "profile",
                "tickets": info.count("Ticket Number:"),
                "text": info,
            }))
            return new

        agent = agent_for_node(node)
        for msg in as_list(update.get("messages")):
            if isinstance(msg, AIMessage):
                new.extend(self._consume_ai(agent, msg))
            else:
                new.extend(self._consume_tool(node, agent, msg))
        return new

    def _consume_ai(self, agent: str, msg: AIMessage) -> list[dict]:
        self._saw_agent(agent)
        new: list[dict] = []
        text = message_text(msg.content)
        calls = msg.tool_calls or []

        if calls and text:
            self.last_thought = text
            new.append(self._add({"kind": "thought", "agent": agent, "text": text}))

        for call in calls:
            name, args = call["name"], call.get("args", {}) or {}
            self._tool_names[call["id"]] = name
            if name in self.backend.delegation_tools:
                new.append(self._add({
                    "kind": "route",
                    "agent": agent,
                    "target": self.backend.delegation_tools[name],
                    "args": args,
                }))
            elif name == self.backend.escalate_tool:
                new.append(self._add({
                    "kind": "escalate",
                    "agent": agent,
                    "reason": args.get("reason", ""),
                }))
            else:
                new.append(self._add({
                    "kind": "tool_call",
                    "agent": agent,
                    "tool": name,
                    "args": args,
                    "sensitive": name in self.backend.sensitive_tools,
                }))

        if not calls and text:
            self.final_text = text
            new.append(self._add({"kind": "response", "agent": agent}))
        return new

    def _consume_tool(self, node: str, agent: str, msg: Any) -> list[dict]:
        # handle_tool_error() in services/utils.py returns plain dicts, ToolNode returns ToolMessages.
        if isinstance(msg, ToolMessage):
            call_id, name, content = msg.tool_call_id, msg.name, msg.content
        elif isinstance(msg, dict):
            call_id, name, content = msg.get("tool_call_id"), msg.get("name"), msg.get("content", "")
        else:
            return []

        if node.startswith("enter_"):
            self._saw_agent(agent)
            return [self._add({"kind": "handoff", "agent": agent})]

        name = name or self._tool_names.get(call_id, "tool")
        content_text = content if isinstance(content, str) else json.dumps(content, default=str)
        return [self._add({
            "kind": "tool_result",
            "agent": agent,
            "tool": name,
            "content": content_text,
            "is_error": content_text.startswith("Error:"),
        })]

    def summary_label(self) -> str:
        path = " → ".join(agent_label(a, with_icon=False) for a in self.agents) or "Agents"
        n = len(self.steps)
        return f"{path} · {n} step{'s' if n != 1 else ''}"


def pending_approvals(backend: Backend, config: dict) -> list[dict]:
    """Tool calls waiting for human approval, or [] if the graph isn't paused on one."""
    snapshot = backend.graph.get_state(config)
    if not snapshot.next or not set(snapshot.next) <= backend.interrupt_nodes:
        return []
    messages = snapshot.values.get("messages", [])
    if not messages or not isinstance(messages[-1], AIMessage):
        return []
    return [
        {"id": tc["id"], "name": tc["name"], "args": tc.get("args", {}) or {}}
        for tc in messages[-1].tool_calls or []
    ]


def explain_error(exc: Exception, qdrant_url: str) -> str:
    name, text = type(exc).__name__, str(exc)
    lowered = text.lower()
    if name == "AuthenticationError" or "incorrect api key" in lowered:
        return "OpenAI rejected the API key. Check the key in the sidebar."
    if name == "GraphRecursionError":
        return "The agents hit the step limit. Raise **Max graph steps** in the sidebar and try again."
    if "must be followed by tool messages" in lowered or "tool_call_id" in lowered:
        return (
            "The conversation state contains an unanswered tool call, so OpenAI refused the "
            "request. Start a **New conversation** from the sidebar to continue."
        )
    if name in ("NotFoundError",) and "model" in lowered:
        return "That model isn't available for this API key. Pick another model in the sidebar."
    if "qdrant" in lowered or "connection refused" in lowered or name == "ResponseHandlingException":
        return f"Couldn't reach the Qdrant vector database at `{qdrant_url}`. Is it running?"
    return "Something went wrong while the agents were working on this."


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------
def code_block(text: str, language: str = "text") -> None:
    try:
        st.code(text, language=language, wrap_lines=True)
    except TypeError:  # older Streamlit without wrap_lines
        st.code(text, language=language)


def parse_tool_content(content: str) -> Any:
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(content)
        except (ValueError, SyntaxError, TypeError):
            continue
    return content


def truncate(text: str, show_raw: bool) -> str:
    if show_raw or len(text) <= TOOL_RESULT_PREVIEW_CHARS:
        return text
    return text[:TOOL_RESULT_PREVIEW_CHARS].rstrip() + " …"


def render_tool_result(step: dict, show_raw: bool) -> None:
    tool = step["tool"]
    if step["is_error"]:
        st.markdown(f"⚠️ `{tool}` failed")
        code_block(truncate(step["content"], show_raw))
        return

    data = parse_tool_content(step["content"])
    if isinstance(data, list) and all(isinstance(r, dict) for r in data):
        st.markdown(f"📥 `{tool}` returned **{len(data)}** result{'s' if len(data) != 1 else ''}")
        if not data:
            return
        if show_raw:
            st.json(data, expanded=False)
        else:
            # Compact retrieval view: drop the raw chunk text, keep ids/names + similarity.
            rows = [
                {k: (round(v, 3) if k == "similarity" and isinstance(v, float) else v)
                 for k, v in row.items() if k != "chunk"}
                for row in data
            ]
            st.dataframe(rows, hide_index=True)
    else:
        st.markdown(f"📥 `{tool}` responded")
        code_block(truncate(str(data), show_raw))


def render_step(step: dict, show_raw: bool) -> None:
    kind = step["kind"]
    if kind == "profile":
        st.markdown(f"📋 **Loaded passenger profile** — {step['tickets']} booked ticket(s)")
        if show_raw and step.get("text"):
            code_block(step["text"])
    elif kind == "thought":
        st.markdown(f"💭 **{agent_label(step['agent'])}**: _{step['text']}_")
    elif kind == "route":
        st.markdown(
            f"🔀 **{agent_label(step['agent'])}** routed the request to "
            f"**{agent_label(step['target'])}**"
        )
        if step["args"]:
            st.json(step["args"], expanded=show_raw)
    elif kind == "handoff":
        st.markdown(f"🤝 **{agent_label(step['agent'])}** took over")
    elif kind == "escalate":
        reason = f" — _{step['reason']}_" if step.get("reason") else ""
        st.markdown(f"↩️ **{agent_label(step['agent'])}** handed control back to the Primary Assistant{reason}")
    elif kind == "tool_call":
        lock = " · 🔒 _requires approval_" if step["sensitive"] else ""
        st.markdown(f"🔧 **{agent_label(step['agent'])}** called `{step['tool']}`{lock}")
        if step["args"]:
            st.json(step["args"], expanded=show_raw)
    elif kind == "tool_result":
        render_tool_result(step, show_raw)
    elif kind == "response":
        st.markdown(f"💬 **{agent_label(step['agent'])}** wrote the reply")
    elif kind == "approval":
        tools = ", ".join(f"`{t}`" for t in step["tools"])
        st.markdown(f"⏸️ **Paused** — waiting for your approval to run {tools}")
    elif kind == "decision":
        if step["approved"]:
            st.markdown("✅ **You approved** the pending action")
        else:
            st.markdown(f"🚫 **You rejected** the pending action — _{step['reason']}_")
    elif kind == "error":
        st.markdown(f"❌ **{step['error_type']}**")
        code_block(truncate(step["detail"], show_raw))


def render_history(show_raw: bool) -> None:
    for entry in st.session_state.messages:
        avatar = USER_AVATAR if entry["role"] == "user" else ASSISTANT_AVATAR
        with st.chat_message(entry["role"], avatar=avatar):
            if entry.get("trace"):
                icon = {"error": "❌", "paused": "⏸️"}.get(entry.get("state"), "🧠")
                with st.expander(f"{icon} {entry['label']}", expanded=False):
                    for step in entry["trace"]:
                        render_step(step, show_raw)
            st.markdown(entry["content"])


def render_approval_card(pending: list[dict]) -> None:
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        with st.container(border=True):
            st.markdown("#### 🔒 Approval needed")
            st.caption(
                "This action changes a booking. Review it, then approve or tell the "
                "assistant what to do instead."
            )
            for call in pending:
                st.markdown(f"**`{call['name']}`**")
                if call["args"]:
                    st.json(call["args"], expanded=True)
            st.text_input(
                "Reason for rejecting (optional)",
                key="deny_reason",
                placeholder="e.g. I'd prefer a different date",
            )
            col_approve, col_deny = st.columns(2)
            col_approve.button(
                "✅ Approve", type="primary", use_container_width=True,
                on_click=queue_action, args=({"type": "approve"},),
            )
            col_deny.button(
                "🚫 Reject", use_container_width=True,
                on_click=queue_action, args=({"type": "deny"},),
            )


def render_welcome() -> None:
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        st.markdown(
            "Hi! I can help with your **flights**, **hotels**, **car rentals** and "
            "**excursions**, and answer questions about company policy. "
            "What can I do for you?"
        )
    cols = st.columns(2)
    for i, prompt in enumerate(SUGGESTED_PROMPTS):
        cols[i % 2].button(
            prompt, key=f"suggest_{i}", use_container_width=True,
            on_click=queue_prompt, args=(prompt,),
        )


# --------------------------------------------------------------------------------------
# Running the graph
# --------------------------------------------------------------------------------------
def run_graph(
    backend: Backend,
    graph_input: Any,
    config: dict,
    *,
    show_raw: bool,
    expand_live: bool,
    qdrant_url: str,
    prefix_steps: list[dict] | None = None,
) -> dict:
    """Stream one run of the graph into a live status box and return the history entry."""
    recorder = TurnRecorder(backend)
    for step in prefix_steps or []:
        recorder.steps.append(step)

    state, content = "complete", None
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        status = st.status("🧭 Routing your request…", expanded=expand_live)
        with status:
            for step in prefix_steps or []:
                render_step(step, show_raw)
            try:
                for event in backend.graph.stream(graph_input, config, stream_mode="updates"):
                    for node, update in event.items():
                        if node.startswith("__") or not isinstance(update, dict):
                            continue  # e.g. "__interrupt__" markers
                        for step in recorder.consume(node, update):
                            render_step(step, show_raw)
                        status.update(
                            label=f"{agent_label(agent_for_node(node))} · step {len(recorder.steps)}…"
                        )

                pending = pending_approvals(backend, config)
                if pending:
                    state = "paused"
                    step = {"kind": "approval", "tools": [p["name"] for p in pending]}
                    recorder.steps.append(step)
                    render_step(step, show_raw)
                    content = recorder.last_thought or (
                        "Before I go ahead, I need your confirmation for the action below."
                    )
                else:
                    content = recorder.final_text or "_The assistant didn't produce a reply._"
            except Exception as exc:  # noqa: BLE001 - show any backend failure in the UI
                log.exception("Graph run failed")
                state = "error"
                step = {"kind": "error", "error_type": type(exc).__name__, "detail": str(exc)}
                recorder.steps.append(step)
                render_step(step, show_raw)
                content = f"Sorry — {explain_error(exc, qdrant_url)}"

        label = recorder.summary_label()
        if state == "paused":
            label = f"Paused for approval · {label}"
        status.update(
            label=label,
            state="error" if state == "error" else "complete",
            expanded=False,
        )
        st.markdown(content)

    return {
        "role": "assistant",
        "content": content,
        "trace": recorder.steps,
        "label": label,
        "state": state,
    }


def denial_input(pending: list[dict], reason: str) -> dict:
    # One ToolMessage per pending call: OpenAI requires every tool_call_id to be answered.
    return {
        "messages": [
            ToolMessage(tool_call_id=call["id"], content=DENIAL_TEMPLATE.format(reason=reason))
            for call in pending
        ]
    }


# --------------------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "messages": [],
        "thread_id": str(uuid.uuid4()),
        "signature": None,
        "queued_action": None,
        "queued_prompt": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_conversation() -> None:
    st.session_state.messages = []
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.queued_action = None
    st.session_state.queued_prompt = None


def queue_action(action: dict) -> None:
    if action["type"] == "deny":
        # Read the reason at click time so text typed just before clicking isn't lost.
        reason = (st.session_state.get("deny_reason") or "").strip()
        action = {**action, "reason": reason or "No reason given."}
    st.session_state.queued_action = action


def queue_prompt(prompt: str) -> None:
    st.session_state.queued_prompt = prompt


# --------------------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------------------
@dataclass
class Settings:
    openai_key: str
    key_source: str
    qdrant_url: str
    model: str | None
    temperature: float
    passenger_id: str
    recursion_limit: int
    show_raw: bool
    expand_live: bool


def render_sidebar() -> Settings:
    env_key = os.environ.get("OPENAI_API_KEY", "") or secret_from_streamlit("OPENAI_API_KEY")

    with st.sidebar:
        st.header("⚙️ Settings")

        # Settings that rebuild the backend live in a form so they only apply on submit.
        with st.form("backend_settings", border=False):
            st.subheader("🔑 API keys")
            ui_key = st.text_input(
                "OpenAI API key",
                type="password",
                key="openai_key_input",
                placeholder="sk-…",
                help="Used for the agents and for query embeddings. Kept only in this "
                     "browser session; never written to disk.",
            )
            if env_key and not ui_key:
                st.caption("Using `OPENAI_API_KEY` from your environment / secrets.")
            with st.expander("LangSmith tracing (optional)"):
                ls_key = st.text_input("LangSmith API key", type="password", key="ls_key_input")
                ls_project = st.text_input(
                    "Project", key="ls_project_input",
                    value=os.environ.get("LANGCHAIN_PROJECT", ""),
                )

            st.subheader("🤖 Agent parameters")
            model_label = st.selectbox("Model", list(MODEL_OPTIONS), key="model_input")
            temperature = st.slider(
                "Temperature", 0.0, 1.0, 1.0, 0.1, key="temperature_input",
                help="The backend default is 1.0. Lower values make answers more consistent.",
            )
            passenger_id = st.text_input(
                "Passenger ID", value=DEFAULT_PASSENGER_ID, key="passenger_input",
                help="Which passenger's bookings the agents can see and change.",
            )
            qdrant_url = st.text_input(
                "Qdrant URL",
                value=os.environ.get("QDRANT_URL", "http://localhost:6333"),
                key="qdrant_input",
            )
            st.form_submit_button("Apply settings", type="primary", use_container_width=True)
            st.caption("Changing these starts a new conversation.")

        recursion_limit = st.slider(
            "Max graph steps", 10, 100, 25, 5,
            help="LangGraph recursion limit per turn — caps how many agent/tool hops a single message can take.",
        )

        st.subheader("🧠 Thought process")
        show_raw = st.toggle("Show raw tool payloads", value=False)
        expand_live = st.toggle("Expand steps while agents work", value=True)

        st.subheader("🔌 Vector database")
        ok, error, counts = check_qdrant(qdrant_url)
        if not ok:
            st.error(f"Qdrant unreachable at `{qdrant_url}`", icon="🔴")
            st.caption(error[:200])
        elif len(counts) < len(EXPECTED_COLLECTIONS):
            missing = [c for c in EXPECTED_COLLECTIONS if c not in counts]
            st.warning(
                "Connected, but missing collections: " + ", ".join(missing)
                + ". Run the vectorizer first.", icon="🟠",
            )
        else:
            st.success(f"Connected · {sum(counts.values()):,} vectors", icon="🟢")

        st.subheader("💬 Session")
        st.button("🧹 New conversation", use_container_width=True, on_click=reset_conversation)
        if st.session_state.messages:
            st.download_button(
                "⬇️ Download transcript",
                data=json.dumps(st.session_state.messages, indent=2, default=str),
                file_name=f"support-chat-{st.session_state.thread_id[:8]}.json",
                mime="application/json",
                use_container_width=True,
            )
        st.caption(f"Thread `{st.session_state.thread_id[:8]}`")

        if GRAPH_IMAGE.exists():
            with st.expander("🗺️ Agent graph"):
                st.image(str(GRAPH_IMAGE))

    configure_langsmith(ls_key, ls_project)
    return Settings(
        openai_key=ui_key or env_key,
        key_source="sidebar" if ui_key else "environment",
        qdrant_url=qdrant_url.strip(),
        model=MODEL_OPTIONS[model_label],
        temperature=float(temperature),
        passenger_id=passenger_id.strip(),
        recursion_limit=int(recursion_limit),
        show_raw=show_raw,
        expand_live=expand_live,
    )


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=ASSISTANT_AVATAR, layout="centered")
    init_state()
    settings = render_sidebar()

    st.title(f"{ASSISTANT_AVATAR} {APP_TITLE}")
    st.caption("Multi-agent RAG support · flights, hotels, car rentals & excursions")

    if not settings.openai_key:
        st.info("Add your **OpenAI API key** in the sidebar and click **Apply settings** to start.", icon="🔑")
        st.stop()
    if not settings.passenger_id:
        st.warning("Enter a passenger ID in the sidebar.", icon="🪪")
        st.stop()

    # A new backend configuration or passenger means a fresh thread.
    signature = (
        fingerprint(settings.openai_key), settings.qdrant_url, settings.model,
        settings.temperature, settings.passenger_id,
    )
    if st.session_state.signature not in (None, signature) and st.session_state.messages:
        reset_conversation()
        st.toast("Settings changed — started a new conversation.", icon="🔄")
    st.session_state.signature = signature

    try:
        with st.spinner("Loading agents (the first run downloads the travel database)…"):
            backend = load_backend(
                signature[0], settings.qdrant_url, settings.model,
                settings.temperature, _api_key=settings.openai_key,
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("Backend failed to load")
        st.error(f"Couldn't initialise the backend: {exc}", icon="🚨")
        st.stop()

    st.caption(f"Passenger `{settings.passenger_id}` · model `{backend.model_name}`")

    config = {
        "configurable": {
            "passenger_id": settings.passenger_id,
            "thread_id": st.session_state.thread_id,
        },
        "recursion_limit": settings.recursion_limit,
    }
    run = lambda graph_input, prefix=None: run_graph(  # noqa: E731
        backend, graph_input, config,
        show_raw=settings.show_raw, expand_live=settings.expand_live,
        qdrant_url=settings.qdrant_url, prefix_steps=prefix,
    )

    if not st.session_state.messages and not st.session_state.queued_prompt:
        render_welcome()
    render_history(settings.show_raw)

    pending = pending_approvals(backend, config)
    typed = st.chat_input(
        "Or type what you'd like changed instead…" if pending else "How can we help you today?"
    )
    action = st.session_state.queued_action
    prompt = typed or st.session_state.queued_prompt
    st.session_state.queued_action = None
    st.session_state.queued_prompt = None

    # 1) Approval buttons.
    if action and pending:
        if action["type"] == "approve":
            names = ", ".join(f"`{p['name']}`" for p in pending)
            user_text = f"✅ Approved {names}"
            graph_input, decision = None, {"kind": "decision", "approved": True}
        else:
            user_text = f"🚫 Rejected — {action['reason']}"
            graph_input = denial_input(pending, action["reason"])
            decision = {"kind": "decision", "approved": False, "reason": action["reason"]}
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(user_text)
        st.session_state.messages.append(run(graph_input, [decision]))
        st.session_state.pop("deny_reason", None)
        st.rerun()

    # 2) A typed/suggested message.
    elif prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(prompt)
        if pending:
            # Same semantics as the CLI: any reply other than approval rejects the
            # pending action, with the message passed to the agent as the reason.
            decision = {"kind": "decision", "approved": False, "reason": prompt}
            st.session_state.messages.append(run(denial_input(pending, prompt), [decision]))
        else:
            st.session_state.messages.append(run({"messages": [("user", prompt)]}))
        st.rerun()

    # 3) Idle: show the approval card if the graph is paused.
    elif pending:
        render_approval_card(pending)


if __name__ == "__main__":
    main()
