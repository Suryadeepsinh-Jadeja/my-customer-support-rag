from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from customer_support_chat.app.services.tools import (
    search_car_rentals,
    book_car_rental,
    update_car_rental,
    cancel_car_rental,
    lookup_policy,
)
from customer_support_chat.app.services.assistants.assistant_base import (
    Assistant,
    CompleteOrEscalate,
    SUPPORT_GUIDELINES,
    current_time,
)

# Car rental assistant prompt
car_rental_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a specialized assistant for handling car rental bookings. "
            "The primary assistant delegates work to you whenever the user needs help booking, changing or cancelling a car rental. "
            "Search for available car rentals based on the user's preferences and confirm the booking details with the customer. "
            "If the customer has not said where or when they need the car, use their flight information below to suggest a "
            "location and dates, and ask them to confirm. "
            "For rules such as driver age, fuel, insurance or cancellation fees, use `lookup_policy`. "
            "When searching, be persistent. Expand your query bounds if the first search returns no results. "
            "If you need more information or the customer changes their mind, escalate the task back to the main assistant. "
            "Remember that a booking isn't completed until after the relevant tool has successfully been used."
            "\n\nCurrent user flight information:\n<Flights>\n{user_info}\n</Flights>"
            "\nCurrent time: {time}."
            "\n\nIf the user needs help, and none of your tools are appropriate for it, then "
            '"CompleteOrEscalate" the dialog to the host assistant. Do not waste the user\'s time. Do not make up invalid tools or functions.'
            "\n\nSome examples for which you should CompleteOrEscalate:\n"
            " - 'what's the weather like this time of year?'\n"
            " - 'What flights are available?'\n"
            " - 'nevermind I think I'll book separately'\n"
            " - 'Oh wait I haven't booked my flight yet I'll do that first'\n"
            " - 'Car rental booking confirmed'"
            + SUPPORT_GUIDELINES,
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=current_time)

# Car rental tools
book_car_rental_safe_tools = [search_car_rentals, lookup_policy]
book_car_rental_sensitive_tools = [book_car_rental, update_car_rental, cancel_car_rental]
book_car_rental_tools = book_car_rental_safe_tools + book_car_rental_sensitive_tools


def build_car_rental_assistant(llm: BaseChatModel) -> Assistant:
    runnable = car_rental_prompt | llm.bind_tools(book_car_rental_tools + [CompleteOrEscalate])
    return Assistant(runnable, name="car_rental_assistant")
