
"""
Streamlit UI for the Multi-Agent RAG Customer Support System.

Flow:
User
  ↓
Primary Assistant
  ↓
Specialized Assistant
  ↓
Tools / Qdrant / Travel Database
  ↓
Final Response
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage

# ============================================================
# PATH / ENVIRONMENT
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent

os.chdir(REPO_ROOT)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Multi-Agent RAG Customer Support",
    page_icon="✈️",
    layout="wide",
)

# ============================================================
# CONSTANTS
# ============================================================

QDRANT_URL = os.getenv(
    "QDRANT_URL",
    "http://localhost:6333",
)

PASSENGER_ID = os.getenv(
    "PASSENGER_ID",
    "5102 899977",
)

GRAPH_IMAGE = REPO_ROOT / "graphs" / "multi-agent-rag-system-graph.png"

# ============================================================
# SESSION STATE
# ============================================================

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "graph" not in st.session_state:
    st.session_state.graph = None

# ============================================================
# LOAD BACKEND
# ============================================================

@st.cache_resource
def load_graph():

    # Import only after environment variables are loaded.
    from customer_support_chat.app.graph import multi_agentic_graph

    return multi_agentic_graph


# ============================================================
# QDRANT CHECK
# ============================================================

def check_qdrant():

    try:

        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=QDRANT_URL,
            timeout=3,
        )

        collections = client.get_collections().collections

        names = [c.name for c in collections]

        return True, names

    except Exception as e:

        return False, str(e)


# ============================================================
# MESSAGE HELPERS
# ============================================================

def get_message_text(content):

    if isinstance(content, str):
        return content

    if isinstance(content, list):

        result = []

        for item in content:

            if isinstance(item, dict):

                if "text" in item:
                    result.append(item["text"])

            else:
                result.append(str(item))

        return "\n".join(result)

    return str(content)


def show_agent_step(node, update):

    st.write(f"### 🔹 {node}")

    if not isinstance(update, dict):
        return

    messages = update.get("messages", [])

    if not isinstance(messages, list):
        messages = [messages]

    for message in messages:

        # ----------------------------------------------------
        # AI MESSAGE
        # ----------------------------------------------------

        if isinstance(message, AIMessage):

            text = get_message_text(message.content)

            if text:
                st.info(text)

            # Tool calls
            for tool in message.tool_calls or []:

                tool_name = tool.get("name", "unknown")

                arguments = tool.get("args", {})

                st.markdown(
                    f"🔧 **Tool called:** `{tool_name}`"
                )

                if arguments:
                    st.json(arguments)

        # ----------------------------------------------------
        # TOOL MESSAGE
        # ----------------------------------------------------

        elif isinstance(message, ToolMessage):

            st.success(
                f"📥 Tool result: `{message.name}`"
            )

            content = get_message_text(message.content)

            if len(content) > 1500:
                content = content[:1500] + "\n..."

            st.code(content)


# ============================================================
# RUN GRAPH
# ============================================================

def run_query(query):

    graph = load_graph()

    config = {
        "configurable": {
            "passenger_id": PASSENGER_ID,
            "thread_id": st.session_state.thread_id,
        },
        "recursion_limit": 50,
    }

    final_answer = None

    trace = []

    with st.status(
        "🧭 Running Multi-Agent RAG workflow...",
        expanded=True,
    ) as status:

        try:

            for event in graph.stream(
                {
                    "messages": [
                        ("user", query)
                    ]
                },
                config,
                stream_mode="updates",
            ):

                for node, update in event.items():

                    if node.startswith("__"):
                        continue

                    trace.append(node)

                    show_agent_step(
                        node,
                        update,
                    )

                    # Look for final AI response
                    if isinstance(update, dict):

                        messages = update.get(
                            "messages",
                            [],
                        )

                        if not isinstance(
                            messages,
                            list,
                        ):
                            messages = [messages]

                        for message in messages:

                            if isinstance(
                                message,
                                AIMessage,
                            ):

                                text = get_message_text(
                                    message.content
                                )

                                if (
                                    text
                                    and not message.tool_calls
                                ):
                                    final_answer = text

            status.update(
                label="✅ Multi-Agent workflow completed",
                state="complete",
            )

        except Exception as e:

            status.update(
                label="❌ Workflow failed",
                state="error",
            )

            st.error(
                f"{type(e).__name__}: {e}"
            )

            return None

    return final_answer


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title("⚙️ System Status")

    # --------------------------------------------------------
    # Gemini
    # --------------------------------------------------------

    st.subheader("🤖 LLM")

    gemini_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )

    if gemini_key:

        st.success(
            "Gemini API key detected",
            icon="🟢",
        )

        st.caption(
            "The key is loaded from the environment."
        )

    else:

        st.warning(
            "Gemini API key not detected",
            icon="🟠",
        )

    # --------------------------------------------------------
    # QDRANT
    # --------------------------------------------------------

    st.subheader("🗄️ Vector Database")

    qdrant_ok, qdrant_info = check_qdrant()

    if qdrant_ok:

        st.success(
            "Qdrant connected",
            icon="🟢",
        )

        st.caption(
            f"URL: {QDRANT_URL}"
        )

        st.write("Collections:")

        for collection in qdrant_info:

            st.code(collection)

    else:

        st.error(
            "Qdrant unavailable",
            icon="🔴",
        )

        st.caption(
            str(qdrant_info)
        )

    # --------------------------------------------------------
    # PASSENGER
    # --------------------------------------------------------

    st.subheader("👤 Passenger")

    st.code(PASSENGER_ID)

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    st.subheader("💬 Session")

    st.caption(
        f"Thread: {st.session_state.thread_id[:8]}"
    )

    if st.button(
        "🧹 New Conversation",
        use_container_width=True,
    ):

        st.session_state.messages = []

        st.session_state.thread_id = str(
            uuid.uuid4()
        )

        st.rerun()

    # --------------------------------------------------------
    # GRAPH
    # --------------------------------------------------------

    if GRAPH_IMAGE.exists():

        st.subheader("🗺️ Agent Architecture")

        with st.expander(
            "Show Multi-Agent Graph"
        ):

            st.image(
                str(GRAPH_IMAGE),
                use_container_width=True,
            )


# ============================================================
# MAIN PAGE
# ============================================================

st.title(
    "✈️ Multi-Agent RAG Customer Support"
)

st.caption(
    "Gemini + LangGraph + Qdrant + Travel Database"
)

# ============================================================
# EXPLANATION
# ============================================================

with st.expander(
    "🔎 What happens when I ask a question?"
):

    st.markdown(
        """
### Multi-Agent Workflow

**1. User Query**

The user asks a travel-support question.

↓

**2. Primary Assistant**

The primary assistant understands the user's intent.

↓

**3. Agent Routing**

The request is delegated to the appropriate specialized assistant.

Examples:

- Flight → Flight Assistant
- Hotel → Hotel Assistant
- Car → Car Rental Assistant
- Excursion → Excursion Assistant

↓

**4. Tools / RAG**

The specialized assistant can use tools and retrieve
information from Qdrant.

↓

**5. Gemini**

Gemini processes the request and retrieved information.

↓

**6. Final Response**

The result is returned to the user.
"""
    )


# ============================================================
# SUGGESTED DEMO
# ============================================================

st.subheader("🎯 Demo Questions")

demo_questions = [
    "What is the status of my flight from BSL to ATH?",
    "What flights do I currently have booked?",
    "Can I change my flight?",
    "Find me a hotel in Basel",
]

cols = st.columns(2)

for i, question in enumerate(demo_questions):

    if cols[i % 2].button(
        question,
        use_container_width=True,
    ):

        st.session_state.messages.append(
            {
                "role": "user",
                "content": question,
            }
        )

        st.rerun()


# ============================================================
# CHAT HISTORY
# ============================================================

for message in st.session_state.messages:

    with st.chat_message(
        message["role"]
    ):

        st.markdown(
            message["content"]
        )


# ============================================================
# CHAT INPUT
# ============================================================

query = st.chat_input(
    "Ask about flights, hotels, car rentals or excursions..."
)


# Handle demo button
if (
    st.session_state.messages
    and st.session_state.messages[-1]["role"] == "user"
    and st.session_state.messages[-1].get("processed") != True
):

    last_message = st.session_state.messages[-1]

    if "processed" not in last_message:

        last_message["processed"] = True

        query = last_message["content"]


# ============================================================
# PROCESS QUERY
# ============================================================

if query:

    # Display user
    with st.chat_message(
        "user"
    ):

        st.markdown(query)

    # Store
    st.session_state.messages.append(
        {
            "role": "user",
            "content": query,
            "processed": True,
        }
    )

    # Run LangGraph
    answer = run_query(query)

    if answer:

        with st.chat_message(
            "assistant"
        ):

            st.markdown(answer)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
            }
        )

    st.rerun()