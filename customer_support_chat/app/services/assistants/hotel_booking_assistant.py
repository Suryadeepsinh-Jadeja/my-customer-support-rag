from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from customer_support_chat.app.services.tools import (
    search_hotels,
    book_hotel,
    update_hotel,
    cancel_hotel,
    lookup_policy,
)
from customer_support_chat.app.services.assistants.assistant_base import (
    Assistant,
    CompleteOrEscalate,
    SUPPORT_GUIDELINES,
    current_time,
)

# Hotel booking assistant prompt
hotel_booking_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a specialized assistant for handling hotel bookings. "
            "The primary assistant delegates work to you whenever the user needs help booking, changing or cancelling a hotel. "
            "Search for available hotels based on the user's preferences and confirm the booking details with the customer. "
            "If the customer has not said where or when they need the hotel, use their flight information below to suggest a "
            "location and dates, and ask them to confirm. "
            "For check-in times, cancellation or change rules, use `lookup_policy`. "
            "When searching, be persistent. Expand your query bounds if the first search returns no results. "
            "If you need more information or the customer changes their mind, escalate the task back to the main assistant. "
            "Remember that a booking isn't completed until after the relevant tool has successfully been used."
            "\n\nCurrent user flight information:\n<Flights>\n{user_info}\n</Flights>"
            "\nCurrent time: {time}."
            '\n\nIf the user needs help, and none of your tools are appropriate for it, then "CompleteOrEscalate" the dialog to the host assistant.'
            " Do not waste the user's time. Do not make up invalid tools or functions."
            "\n\nSome examples for which you should CompleteOrEscalate:\n"
            " - 'what's the weather like this time of year?'\n"
            " - 'nevermind I think I'll book separately'\n"
            " - 'I need to figure out transportation while I'm there'\n"
            " - 'Oh wait I haven't booked my flight yet I'll do that first'\n"
            " - 'Hotel booking confirmed'"
            + SUPPORT_GUIDELINES,
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=current_time)

# Hotel booking tools
book_hotel_safe_tools = [search_hotels, lookup_policy]
book_hotel_sensitive_tools = [book_hotel, update_hotel, cancel_hotel]
book_hotel_tools = book_hotel_safe_tools + book_hotel_sensitive_tools


def build_hotel_booking_assistant(llm: BaseChatModel) -> Assistant:
    runnable = hotel_booking_prompt | llm.bind_tools(book_hotel_tools + [CompleteOrEscalate])
    return Assistant(runnable, name="hotel_booking_assistant")
