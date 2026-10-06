"""A scripted stand-in for `LLMService`.

Each model call pops the next scripted step, in call order: the supervisor's
`generate_structured`, then the agent's `generate_with_tools` steps, and `generate` for
summaries. A step may be a callable receiving the call's arguments, so tests can assert on
what the model was shown. Every call is recorded in `calls`.
"""

from typing import Any

from pydantic import BaseModel

from app.agents.supervisor import Intent
from app.services.llm_service import ModelTurn, ToolCall, ToolResult


def call(name: str, **args: Any) -> ModelTurn:
    return ModelTurn(calls=[ToolCall(name, args)])


def reply(text: str) -> ModelTurn:
    return ModelTurn(text=text)


def intent(domain: str, **flags: bool) -> Intent:
    return Intent(domain=domain, **flags)  # type: ignore[arg-type]


class ScriptedLLM:
    def __init__(self, *steps: Any):
        self.steps = list(steps)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def script(self, *steps: Any) -> "ScriptedLLM":
        self.steps.extend(steps)
        return self

    def _next(self, method: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((method, kwargs))
        if not self.steps:
            raise AssertionError(f"ScriptedLLM ran out of steps ({method})")
        step = self.steps.pop(0)
        if callable(step) and not isinstance(step, type):
            step = step(**kwargs)
        if isinstance(step, Exception):
            raise step
        return step

    async def generate_structured(self, **kwargs: Any) -> BaseModel:
        step = self._next("generate_structured", kwargs)
        assert isinstance(step, kwargs["schema"]), f"expected {kwargs['schema']}, got {step!r}"
        return step

    async def generate_with_tools(self, **kwargs: Any) -> ModelTurn:
        kwargs["history"] = list(kwargs["history"])  # snapshot: the agent keeps appending
        step = self._next("generate_with_tools", kwargs)
        return reply(step) if isinstance(step, str) else step

    async def generate(self, **kwargs: Any) -> str:
        step = self._next("generate", kwargs)
        assert isinstance(step, str)
        return step

    # ------------------------------------------------------------ assertions helpers

    def tool_results(self, index: int = -1) -> list[ToolResult]:
        """Tool results the model saw in its `index`-th tool-loop call."""
        loops = [kw for m, kw in self.calls if m == "generate_with_tools"]
        return [h for h in loops[index]["history"] if isinstance(h, ToolResult)]
