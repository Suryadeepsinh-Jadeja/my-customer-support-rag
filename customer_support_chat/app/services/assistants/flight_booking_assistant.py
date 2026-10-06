from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from customer_support_chat.app.services.tools import (
    fetch_user_flight_information,
    search_flights,
    update_ticket_to_new_flight,
    cancel_ticket,
    book_flight,
    lookup_policy,
)
from customer_support_chat.app.services.assistants.assistant_base import (
    Assistant,
    CompleteOrEscalate,
    SUPPORT_GUIDELINES,
    current_time,
)

# Flight booking assistant prompt
flight_booking_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a specialized assistant for handling flight information, updates, cancellations and new flight bookings. "
            "The primary assistant delegates work to you whenever the user needs help with their flights. "
            "Confirm the updated flight details with the customer and inform them of any additional fees, "
            "checking the applicable fees with `lookup_policy` (flight change / cancellation policy) for the ticket's fare class. "
            "To find alternative flights use `search_flights` with IATA airport codes and dates. "
            "A flight change keeps the same origin and destination; a different route needs a cancellation and a new booking. "
            "If the ticket has several flights, pass the flight being replaced as `old_flight_id` to `update_ticket_to_new_flight`. "
            "When searching, be persistent. Expand your query bounds if the first search returns no results. "
            "If you need more information or the customer changes their mind, escalate the task back to the main assistant. "
            "Remember that a booking isn't completed until after the relevant tool has successfully been used."
            "\n\nCurrent user flight information:\n<Flights>\n{user_info}\n</Flights>"
            "\nCurrent time: {time}."
            "\n\nIf the user needs help, and none of your tools are appropriate for it, then "
            '"CompleteOrEscalate" the dialog to the host assistant. Do not waste the user\'s time. Do not make up invalid tools or functions.'
            "\n\nSome examples for which you should CompleteOrEscalate:\n"
            " - 'I also need a hotel'\n"
            " - 'Can you recommend something to do in Basel?'\n"
            " - 'Flight changed, thanks!'"
            + SUPPORT_GUIDELINES,
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=current_time)

# Flight booking tools
update_flight_safe_tools = [search_flights, fetch_user_flight_information, lookup_policy]
update_flight_sensitive_tools = [update_ticket_to_new_flight, cancel_ticket, book_flight]
update_flight_tools = update_flight_safe_tools + update_flight_sensitive_tools


def build_flight_booking_assistant(llm: BaseChatModel) -> Assistant:
    runnable = flight_booking_prompt | llm.bind_tools(update_flight_tools + [CompleteOrEscalate])
    return Assistant(runnable, name="flight_booking_assistant")
