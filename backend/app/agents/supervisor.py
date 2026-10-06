"""Supervisor: classify the message, pick a specialist, run its tool loop.

No graph framework: one structured-output call to route, then a small loop of model
steps in which the backend executes the requested tools and feeds results back.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.agents import tools as tool_registry
from app.agents.prompts import SPECIALISTS, SUPERVISOR_PROMPT, agent_system_prompt
from app.services.llm_service import (
    ChatTurn,
    HistoryItem,
    LLMError,
    LLMRateLimitedError,
    LLMService,
    ToolResult,
)

logger = logging.getLogger("travel.agents")

MAX_STEPS = 6

Domain = Literal["flight", "hotel", "car", "excursion", "document", "policy", "general"]


class Intent(BaseModel):
    domain: Domain
    continues_previous_topic: bool = False
    needs_documents: bool = False
    needs_policy: bool = False
    needs_booking: bool = False


async def route(llm: LLMService, history: list[ChatTurn],
                active_agent: str | None) -> tuple[str, Intent | None]:
    """Pick the specialist for the last message in `history`."""
    lines = [f"{'User' if t.role == 'user' else 'Assistant'}: {t.text[:500]}"
             for t in history[-5:-1]]
    prompt = (
        f"Current specialist: {active_agent or 'none'}\n"
        "<conversation>\n" + "\n".join(lines) + "\n</conversation>\n"
        f"<latest_user_message>\n{history[-1].text}\n</latest_user_message>"
    )
    try:
        intent = await llm.generate_structured(purpose="supervisor", system=SUPERVISOR_PROMPT,
                                               contents=[prompt], schema=Intent)
    except LLMRateLimitedError:
        raise
    except LLMError as exc:  # routing is best effort; any specialist can answer
        logger.warning("routing failed", extra={"error": str(exc)})
        return active_agent or "general", None
    if intent.continues_previous_topic and active_agent in SPECIALISTS:
        return active_agent, intent
    return intent.domain, intent


def hints(intent: Intent | None) -> list[str]:
    if intent is None:
        return []
    out = []
    if intent.needs_documents:
        out.append("Check the user's documents.")
    if intent.needs_policy:
        out.append("Check the company policies.")
    if intent.needs_booking:
        out.append("The user may want to book or change something.")
    return out


@dataclass
class AgentReply:
    text: str
    steps: int


async def run_agent(llm: LLMService, ctx: tool_registry.ToolContext, agent: str,
                    history: list[HistoryItem], *, summary: str | None = None,
                    intent: Intent | None = None) -> AgentReply:
    spec = SPECIALISTS[agent]
    system = agent_system_prompt(agent, summary=summary, hints=hints(intent))
    tool_specs = [tool_registry.TOOLS[name].spec() for name in spec.tools]
    items = list(history)
    for step in range(1, MAX_STEPS + 1):
        turn = await llm.generate_with_tools(purpose=f"agent.{agent}", system=system,
                                             history=items, tools=tool_specs)
        if not turn.calls:
            text = turn.text or "Sorry, I couldn't come up with an answer. Please rephrase."
            return AgentReply(text, step)
        items.append(turn)
        for call in turn.calls:
            result = await tool_registry.execute(ctx, call, spec.tools)
            items.append(ToolResult(call.name, {"untrusted_data": result}))
    return AgentReply("Sorry, that took too many steps. Please ask a more specific question.",
                      MAX_STEPS)
