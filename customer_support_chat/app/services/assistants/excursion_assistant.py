from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from customer_support_chat.app.services.tools import (
    search_trip_recommendations,
    book_excursion,
    update_excursion,
    cancel_excursion,
    lookup_policy,
)
from customer_support_chat.app.services.assistants.assistant_base import (
    Assistant,
    CompleteOrEscalate,
    SUPPORT_GUIDELINES,
    current_time,
)

# Excursion assistant prompt
excursion_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a specialized assistant for handling trip recommendations and excursion bookings. "
            "The primary assistant delegates work to you whenever the user needs trip recommendations or wants to book, change or cancel an excursion. "
            "Search for trip recommendations based on the user's preferences and destination. If the customer does not name a "
            "destination, use the arrival city of their flight below. Present a few options and confirm the booking details with the customer. "
            "For cancellation or weather rules, use `lookup_policy`. "
            "If you need more information or the customer changes their mind, escalate the task back to the main assistant. "
            "When searching, be persistent. Expand your query bounds if the first search returns no results. "
            "Remember that a booking isn't completed until after the relevant tool has successfully been used."
            "\n\nCurrent user flight information:\n<Flights>\n{user_info}\n</Flights>"
            "\nCurrent time: {time}."
            '\n\nIf the user needs help, and none of your tools are appropriate for it, then "CompleteOrEscalate" the dialog to the host assistant. Do not waste the user\'s time. Do not make up invalid tools or functions.'
            "\n\nSome examples for which you should CompleteOrEscalate:\n"
            " - 'nevermind I think I'll book separately'\n"
            " - 'I need to figure out transportation while I'm there'\n"
            " - 'Oh wait I haven't booked my flight yet I'll do that first'\n"
            " - 'Excursion booking confirmed!'"
            + SUPPORT_GUIDELINES,
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=current_time)

# Excursion tools
book_excursion_safe_tools = [search_trip_recommendations, lookup_policy]
book_excursion_sensitive_tools = [book_excursion, update_excursion, cancel_excursion]
book_excursion_tools = book_excursion_safe_tools + book_excursion_sensitive_tools


def build_excursion_assistant(llm: BaseChatModel) -> Assistant:
    runnable = excursion_prompt | llm.bind_tools(book_excursion_tools + [CompleteOrEscalate])
    return Assistant(runnable, name="excursion_assistant")
