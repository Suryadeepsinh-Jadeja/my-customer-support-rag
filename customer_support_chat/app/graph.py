from typing import Callable, Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import tools_condition

from customer_support_chat.app.core.errors import CustomerNotIdentifiedError
from customer_support_chat.app.core.logger import logger
from customer_support_chat.app.core.state import State
from customer_support_chat.app.services.utils import (
    create_tool_node_with_fallback,
    flight_info_to_string,
    create_entry_node,
)
from customer_support_chat.app.services.tools.flights import fetch_user_flight_information
from customer_support_chat.app.services.assistants.assistant_base import (
    CompleteOrEscalate,
    get_llm,
)
from customer_support_chat.app.services.assistants.primary_assistant import (
    build_primary_assistant,
    primary_assistant_tools,
    ToFlightBookingAssistant,
    ToBookCarRental,
    ToHotelBookingAssistant,
    ToBookExcursion,
)
from customer_support_chat.app.services.assistants.flight_booking_assistant import (
    build_flight_booking_assistant,
    update_flight_safe_tools,
    update_flight_sensitive_tools,
)
from customer_support_chat.app.services.assistants.car_rental_assistant import (
    build_car_rental_assistant,
    book_car_rental_safe_tools,
    book_car_rental_sensitive_tools,
)
from customer_support_chat.app.services.assistants.hotel_booking_assistant import (
    build_hotel_booking_assistant,
    book_hotel_safe_tools,
    book_hotel_sensitive_tools,
)
from customer_support_chat.app.services.assistants.excursion_assistant import (
    build_excursion_assistant,
    book_excursion_safe_tools,
    book_excursion_sensitive_tools,
)

# Sensitive tool nodes: the graph pauses before these so the customer can confirm.
interrupt_nodes = [
    "update_flight_sensitive_tools",
    "book_car_rental_sensitive_tools",
    "book_hotel_sensitive_tools",
    "book_excursion_sensitive_tools",
]

NOT_SIGNED_IN = (
    "The customer is not signed in, so no booking information is available. "
    "General policy questions can still be answered; ask the customer to sign in "
    "before discussing or changing their bookings."
)


def user_info(state: State, config: RunnableConfig):
    # Fetch the signed-in customer's flight information (refreshed every turn).
    try:
        flight_info = fetch_user_flight_information.invoke(input={}, config=config)
    except CustomerNotIdentifiedError:
        return {"user_info": NOT_SIGNED_IN}
    except Exception:
        logger.exception("Could not load the customer's flight information")
        return {"user_info": "The customer's booking information is temporarily unavailable."}
    if not flight_info:
        return {"user_info": "The signed-in customer has no booked flights."}
    return {"user_info": flight_info_to_string(flight_info)}


def route_to_workflow(state: State) -> Literal[
    "primary_assistant",
    "update_flight",
    "book_car_rental",
    "book_hotel",
    "book_excursion",
]:
    """If we are in a delegated state, route directly back to the active assistant."""
    dialog_state = state.get("dialog_state")
    if not dialog_state:
        return "primary_assistant"
    return dialog_state[-1]


def pop_dialog_state(state: State) -> dict:
    """Pop the dialog stack and return to the main assistant.

    This lets the full graph explicitly track the dialog flow and delegate control
    to specific sub-graphs."""
    messages = []
    if state["messages"][-1].tool_calls:
        # The LLM requires a response for every tool call it made.
        messages = [
            ToolMessage(
                content="Resuming dialog with the host assistant. Please reflect on the past conversation and assist the user as needed.",
                tool_call_id=tc["id"],
            )
            for tc in state["messages"][-1].tool_calls
        ]
    return {"dialog_state": "pop", "messages": messages}


def _specialist_router(prefix: str, safe_tools: list) -> Callable:
    safe_toolnames = {t.name for t in safe_tools}

    def route(state: State):
        route = tools_condition(state)
        if route == END:
            return END
        tool_calls = state["messages"][-1].tool_calls
        did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
        if did_cancel:
            return "leave_skill"
        if all(tc["name"] in safe_toolnames for tc in tool_calls):
            return f"{prefix}_safe_tools"
        return f"{prefix}_sensitive_tools"

    route.__name__ = f"route_{prefix}"
    return route


def route_primary_assistant(state: State) -> Literal[
    "primary_assistant_tools",
    "enter_update_flight",
    "enter_book_car_rental",
    "enter_book_hotel",
    "enter_book_excursion",
    "__end__",
]:
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        tool_name = tool_calls[0]["name"]
        if tool_name == ToFlightBookingAssistant.__name__:
            return "enter_update_flight"
        elif tool_name == ToBookCarRental.__name__:
            return "enter_book_car_rental"
        elif tool_name == ToHotelBookingAssistant.__name__:
            return "enter_book_hotel"
        elif tool_name == ToBookExcursion.__name__:
            return "enter_book_excursion"
        else:
            return "primary_assistant_tools"
    return END


def build_graph(
    llm: Optional[BaseChatModel] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    """Build and compile the multi-agent graph.

    `llm` and `checkpointer` are injectable so tests can use a scripted model and
    deployments can swap MemorySaver for a persistent checkpointer."""
    llm = llm or get_llm()
    builder = StateGraph(State)

    builder.add_node("fetch_user_info", user_info)
    builder.add_edge(START, "fetch_user_info")
    builder.add_conditional_edges("fetch_user_info", route_to_workflow)

    specialists = [
        # (node prefix, entry label, assistant, safe tools, sensitive tools)
        ("update_flight", "Flight Updates & Booking Assistant",
         build_flight_booking_assistant(llm), update_flight_safe_tools, update_flight_sensitive_tools),
        ("book_car_rental", "Car Rental Assistant",
         build_car_rental_assistant(llm), book_car_rental_safe_tools, book_car_rental_sensitive_tools),
        ("book_hotel", "Hotel Booking Assistant",
         build_hotel_booking_assistant(llm), book_hotel_safe_tools, book_hotel_sensitive_tools),
        ("book_excursion", "Trip Recommendation Assistant",
         build_excursion_assistant(llm), book_excursion_safe_tools, book_excursion_sensitive_tools),
    ]

    for prefix, label, assistant, safe_tools, sensitive_tools in specialists:
        builder.add_node(f"enter_{prefix}", create_entry_node(label, prefix))
        builder.add_node(prefix, assistant)
        builder.add_edge(f"enter_{prefix}", prefix)
        builder.add_node(f"{prefix}_safe_tools", create_tool_node_with_fallback(safe_tools))
        # The sensitive node also knows the safe tools, so a turn that mixes both
        # kinds of calls is executed in full (after confirmation).
        builder.add_node(
            f"{prefix}_sensitive_tools",
            create_tool_node_with_fallback(sensitive_tools + safe_tools),
        )
        builder.add_edge(f"{prefix}_safe_tools", prefix)
        builder.add_edge(f"{prefix}_sensitive_tools", prefix)
        builder.add_conditional_edges(
            prefix,
            _specialist_router(prefix, safe_tools),
            [f"{prefix}_safe_tools", f"{prefix}_sensitive_tools", "leave_skill", END],
        )

    # Shared exit node: specialists hand control back to the primary assistant.
    builder.add_node("leave_skill", pop_dialog_state)
    builder.add_edge("leave_skill", "primary_assistant")

    # Primary Assistant
    builder.add_node("primary_assistant", build_primary_assistant(llm))
    builder.add_node(
        "primary_assistant_tools", create_tool_node_with_fallback(primary_assistant_tools)
    )
    builder.add_conditional_edges(
        "primary_assistant",
        route_primary_assistant,
        {
            "enter_update_flight": "enter_update_flight",
            "enter_book_car_rental": "enter_book_car_rental",
            "enter_book_hotel": "enter_book_hotel",
            "enter_book_excursion": "enter_book_excursion",
            "primary_assistant_tools": "primary_assistant_tools",
            END: END,
        },
    )
    builder.add_edge("primary_assistant_tools", "primary_assistant")

    # Compile the graph with interrupts
    return builder.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_before=interrupt_nodes,
    )


_graph = None


def get_graph():
    """The application's shared graph instance, built on first use."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def __getattr__(name):
    # Backwards compatible `from customer_support_chat.app.graph import multi_agentic_graph`,
    # built lazily so importing this module never requires an API key.
    if name == "multi_agentic_graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
