"""A deterministic chat model for graph tests.

Each call pops the next scripted step. A step is either an AIMessage or a
callable receiving the prompt messages and returning an AIMessage, so a test
can assert on what the model was shown (e.g. tool results).
"""

import uuid
from typing import Any, Callable, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

Step = Union[AIMessage, Callable[[list[BaseMessage]], AIMessage]]


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
    )


def reply(text: str) -> AIMessage:
    return AIMessage(content=text)


class ScriptedChatModel(BaseChatModel):
    _steps: list = PrivateAttr(default_factory=list)
    _seen: list = PrivateAttr(default_factory=list)

    def script(self, *steps: Step) -> "ScriptedChatModel":
        self._steps.extend(steps)
        return self

    @property
    def calls(self) -> list[list[BaseMessage]]:
        """The prompt messages of every call so far."""
        return self._seen

    @property
    def remaining(self) -> int:
        return len(self._steps)

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._seen.append(list(messages))
        if not self._steps:
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        step = self._steps.pop(0)
        message = step(messages) if callable(step) else step
        # Fresh copy with a unique id so repeated scripts don't collide in state.
        message = message.model_copy(update={"id": f"ai_{uuid.uuid4().hex[:8]}"})
        return ChatResult(generations=[ChatGeneration(message=message)])
