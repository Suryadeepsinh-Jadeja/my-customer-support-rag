from typing import Optional

from langchain_core.runnables import Runnable, RunnableConfig
from customer_support_chat.app.core.state import State
from pydantic import BaseModel
from customer_support_chat.app.core.settings import get_settings
from langchain_google_genai import ChatGoogleGenerativeAI


settings = get_settings()


# Initialize the language model (shared among assistants)
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=settings.GEMINI_API_KEY,
    temperature=1,
)


class Assistant(Runnable):
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def invoke(
        self,
        state: State,
        config: Optional[RunnableConfig] = None,
    ):
        while True:
            result = self.runnable.invoke(state, config)

            # If the assistant did not call a tool,
            # make sure it produced valid content.
            if not result.tool_calls:

                # Case 1: No content at all
                if not result.content:
                    messages = state["messages"] + [
                        ("user", "Respond with a real output.")
                    ]

                    state = {
                        **state,
                        "messages": messages,
                    }

                    continue

                # Case 2: Content is a list
                if isinstance(result.content, list):

                    first_content = result.content[0]

                    # Content item is a dictionary
                    if isinstance(first_content, dict):
                        text = first_content.get("text")

                        if not text:
                            messages = state["messages"] + [
                                ("user", "Respond with a real output.")
                            ]

                            state = {
                                **state,
                                "messages": messages,
                            }

                            continue

                    # Content item is a string
                    elif isinstance(first_content, str):

                        if not first_content.strip():
                            messages = state["messages"] + [
                                ("user", "Respond with a real output.")
                            ]

                            state = {
                                **state,
                                "messages": messages,
                            }

                            continue

            # Valid result
            break

        return {"messages": result}


# Define the CompleteOrEscalate tool
class CompleteOrEscalate(BaseModel):
    """A tool to mark the current task as completed or to escalate control to the main assistant."""

    cancel: bool = True
    reason: str