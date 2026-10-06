"""The one place the application talks to Gemini.

Changing model or provider later means changing this module only. Callers get typed
results (`generate_structured` returns a validated Pydantic object) and typed errors;
prompts and responses are never logged, only metadata (model, latency, sizes).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
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

    async def _call(self, purpose: str, contents: list[Content], config):
        client = self._get_client()
        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.model, contents=self._parts(contents), config=config
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
        response = await self._call(purpose, contents, config)
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
        response = await self._call(purpose, contents, config)
        parsed = response.parsed
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise LLMError("response did not match the schema") from exc


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
    return LLMService(settings.GEMINI_API_KEY, settings.GEMINI_MODEL,
                      settings.LLM_TIMEOUT_SECONDS)
