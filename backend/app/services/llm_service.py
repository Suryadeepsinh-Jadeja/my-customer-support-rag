"""The one place the application talks to Gemini.

Changing model or provider later means changing this module only. Callers get typed
results (`generate_structured` returns a validated Pydantic object) and typed errors;
prompts and responses are never logged, only metadata (model, latency, sizes).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger("travel.llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model could not produce a usable answer."""


class LLMNotConfiguredError(LLMError):
    pass


class LLMRateLimitedError(LLMError):
    pass


@dataclass(frozen=True)
class Blob:
    """Binary input such as a page image."""

    data: bytes
    mime_type: str


Content = str | Blob


@dataclass(frozen=True)
class ChatTurn:
    """A plain text message in a conversation history."""

    role: str  # "user" | "model"
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class ModelTurn:
    """What the model returned: final text, or tool calls the backend must execute.

    `raw` is the SDK content, sent back unchanged so Gemini sees its own thought
    signatures on the next step.
    """

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    response: dict[str, Any]


HistoryItem = ChatTurn | ModelTurn | ToolResult


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


class LLMService:
    def __init__(self, api_key: str, model: str, timeout: float):
        self.model = model
        self.timeout = timeout
        self._api_key = api_key
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        if not self._api_key:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not set")
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @staticmethod
    def _parts(contents: list[Content]):
        from google.genai import types

        return [
            types.Part.from_bytes(data=c.data, mime_type=c.mime_type) if isinstance(c, Blob)
            else types.Part.from_text(text=c)
            for c in contents
        ]

    @staticmethod
    def _history(history: list[HistoryItem]):
        from google.genai import types

        contents: list[types.Content] = []
        for item in history:
            if isinstance(item, ChatTurn):
                contents.append(types.Content(role=item.role,
                                              parts=[types.Part.from_text(text=item.text)]))
            elif isinstance(item, ModelTurn):
                contents.append(item.raw or types.Content(role="model", parts=[
                    types.Part.from_function_call(name=c.name, args=c.args) for c in item.calls
                ] or [types.Part.from_text(text=item.text)]))
            else:
                part = types.Part.from_function_response(name=item.name, response=item.response)
                last = contents[-1] if contents else None
                # Results of parallel calls go back together in one turn.
                if last is not None and last.role == "user" and last.parts and all(
                        p.function_response for p in last.parts):
                    last.parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return contents

    async def _call(self, purpose: str, contents, config):
        client = self._get_client()
        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                ),
                self.timeout,
            )
        except TimeoutError as exc:
            raise LLMError("timeout") from exc
        except Exception as exc:  # the SDK raises several transport/API error types
            text = f"{type(exc).__name__}: {exc}"
            if "429" in text or "RESOURCE_EXHAUSTED" in text:
                raise LLMRateLimitedError("rate limited") from exc
            raise LLMError(type(exc).__name__) from exc
        finally:
            logger.info("llm.call", extra={
                "purpose": purpose, "model": self.model,
                "latency_ms": round((time.perf_counter() - start) * 1000),
            })
        return response

    async def generate(self, *, purpose: str, system: str, contents: list[Content],
                       temperature: float = 0.2) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._call(purpose, self._parts(contents), config)
        return (response.text or "").strip()

    async def generate_structured(self, *, purpose: str, system: str,
                                  contents: list[Content], schema: type[T],
                                  temperature: float = 0.0) -> T:
        """Generate output that must validate against `schema`."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._call(purpose, self._parts(contents), config)
        parsed = response.parsed
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise LLMError("response did not match the schema") from exc

    async def generate_with_tools(self, *, purpose: str, system: str,
                                  history: list[HistoryItem], tools: list[ToolSpec],
                                  temperature: float = 0.2) -> ModelTurn:
        """One model step. The backend executes any returned tool calls itself."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters_json_schema=t.parameters)
                for t in tools
            ])] if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._call(purpose, self._history(history), config)
        calls = [ToolCall(name=c.name or "", args=dict(c.args or {}))
                 for c in response.function_calls or []]
        raw = response.candidates[0].content if response.candidates else None
        if calls:
            return ModelTurn(calls=calls, raw=raw)
        return ModelTurn(text=(response.text or "").strip(), raw=raw)

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        """Unit-length embeddings (768-d). `query=True` for search queries."""
        from google.genai import types

        from app.db.models.rag import EMBEDDING_DIM

        client = self._get_client()
        config = types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBEDDING_DIM,
        )
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 100):  # API batch limit
            try:
                response = await asyncio.wait_for(
                    client.aio.models.embed_content(
                        model=EMBEDDING_MODEL, contents=texts[i:i + 100], config=config
                    ),
                    self.timeout,
                )
            except Exception as exc:
                raise LLMError(f"embedding failed: {type(exc).__name__}") from exc
            for e in response.embeddings or []:
                norm = sum(x * x for x in e.values or []) ** 0.5 or 1.0
                vectors.append([x / norm for x in e.values or []])
        if len(vectors) != len(texts):
            raise LLMError("embedding count mismatch")
        return vectors


EMBEDDING_MODEL = "gemini-embedding-001"


@lru_cache
def get_llm() -> LLMService:
    settings = get_settings()
    if settings.LLM_PROVIDER == "fake":
        from app.services.fake_llm import FakeLLM

        return FakeLLM()
    return LLMService(settings.GEMINI_API_KEY, settings.GEMINI_MODEL,
                      settings.LLM_TIMEOUT_SECONDS)
