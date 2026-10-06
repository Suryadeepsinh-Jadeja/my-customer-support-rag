from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from customer_support_chat.app.services.tools import (
    search_flights,
    lookup_policy,
)
from customer_support_chat.app.services.assistants.assistant_base import (
    Assistant,
    SUPPORT_GUIDELINES,
    current_time,
)
from pydantic import BaseModel, Field

# Define task delegation tools
class ToFlightBookingAssistant(BaseModel):
    """Transfers work to a specialized assistant to handle flight updates, rebookings, cancellations and new flight bookings."""
    request: str = Field(description="Any necessary follow-up questions the update flight assistant should clarify before proceeding.")

class ToBookCarRental(BaseModel):
    """Transfers work to a specialized assistant to handle car rental bookings, changes and cancellations."""
    location: str = Field(default="", description="The location where the user wants to rent a car, if known.")
    start_date: str = Field(default="", description="The start date of the car rental (YYYY-MM-DD), if known.")
    end_date: str = Field(default="", description="The end date of the car rental (YYYY-MM-DD), if known.")
    request: str = Field(description="Any additional information or requests from the user regarding the car rental.")

class ToHotelBookingAssistant(BaseModel):
    """Transfers work to a specialized assistant to handle hotel bookings, changes and cancellations."""
    location: str = Field(default="", description="The location where the user wants to book a hotel, if known.")
    checkin_date: str = Field(default="", description="The check-in date for the hotel (YYYY-MM-DD), if known.")
    checkout_date: str = Field(default="", description="The check-out date for the hotel (YYYY-MM-DD), if known.")
    request: str = Field(description="Any additional information or requests from the user regarding the hotel booking.")

class ToBookExcursion(BaseModel):
    """Transfers work to a specialized assistant to handle trip recommendations and excursion bookings, changes and cancellations."""
    location: str = Field(default="", description="The location where the user wants a recommended trip, if known.")
    request: str = Field(description="Any additional information or requests from the user regarding the trip recommendation.")

# Primary assistant prompt
primary_assistant_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful customer support assistant for Swiss Airlines. "
            "Your primary role is to answer questions about the customer's bookings and company policies, and to route requests. "
            "\n\nHow to handle requests:"
            "\n - Policy / general questions (baggage, check-in, refunds, fees, documents, rental or hotel rules): call `lookup_policy`."
            "\n - Questions about the customer's own flights (ticket, seat, times): answer from the flight information below."
            "\n - Questions that combine both (e.g. 'can I cancel my flight and what refund would I get?'): use the customer's "
            "fare class from the flight information below AND call `lookup_policy`, then combine both into one answer."
            "\n - If a customer requests to change, cancel or book a flight, book or change a car rental, a hotel, or get trip "
            "recommendations, delegate the task to the appropriate specialized assistant by invoking the corresponding tool. "
            "You are not able to make these types of changes yourself. Only the specialized assistants are given permission to do this for the user."
            "\n\nThe user is not aware of the different specialized assistants, so do not mention them; just quietly delegate through function calls. "
            "Provide detailed information to the customer, and always double-check the database before concluding that information is unavailable. "
            "When searching, be persistent. Expand your query bounds if the first search returns no results. "
            "\n\nCurrent user flight information:\n<Flights>\n{user_info}\n</Flights>"
            "\nCurrent time: {time}."
            + SUPPORT_GUIDELINES,
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=current_time)

# Primary assistant tools. Web search was removed on purpose: policy answers must come from
# the verified knowledge base, not from arbitrary web pages.
primary_assistant_tools = [
    search_flights,
    lookup_policy,
]
delegation_tools = [
    ToFlightBookingAssistant,
    ToBookCarRental,
    ToHotelBookingAssistant,
    ToBookExcursion,
]


def build_primary_assistant(llm: BaseChatModel) -> Assistant:
    runnable = primary_assistant_prompt | llm.bind_tools(primary_assistant_tools + delegation_tools)
    return Assistant(runnable, name="primary_assistant")
