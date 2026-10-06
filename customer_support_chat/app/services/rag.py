"""Knowledge retrieval for policy / FAQ questions (the "R" in RAG).

query -> embedding -> vector search (over-fetch) -> cross-encoder rerank
      -> relevance threshold -> top-k chunks with source metadata

The index is built offline by `scripts/ingest.py`; this module only reads it.
"""

import math
import threading
from dataclasses import dataclass, asdict
from functools import lru_cache

from customer_support_chat.app.core.logger import log_event
from customer_support_chat.app.core.settings import get_settings
from vectorizer.app.vectordb.vectordb import VectorDB

KNOWLEDGE_COLLECTION = "knowledge_base_collection"


class KnowledgeBaseUnavailable(RuntimeError):
    """The knowledge index is missing or the vector store cannot be reached."""


@dataclass
class RetrievedChunk:
    text: str
    document_name: str
    section: str
    source: str
    chunk_id: str
    score: float

    def citation(self) -> dict:
        data = asdict(self)
        data.pop("text")
        data["score"] = round(self.score, 3)
        return data


@lru_cache(maxsize=1)
def _get_reranker():
    from sentence_transformers import CrossEncoder
    from vectorizer.app.core.settings import get_settings as get_vectorizer_settings

    return CrossEncoder(get_vectorizer_settings().RERANKER_MODEL)


class KnowledgeRetriever:
    def __init__(self, vectordb: VectorDB | None = None):
        self.settings = get_settings()
        self.vectordb = vectordb or VectorDB(
            table_name="knowledge_base", collection_name=KNOWLEDGE_COLLECTION
        )
        self._checked = False
        self._lock = threading.Lock()

    def _ensure_ready(self):
        if self._checked:
            return
        with self._lock:
            if not self.vectordb.collection_ready():
                raise KnowledgeBaseUnavailable(
                    "Knowledge base index not found. Run `python scripts/ingest.py` first."
                )
            self._checked = True

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        top_k = top_k or self.settings.RAG_TOP_K
        self._ensure_ready()

        try:
            points = self.vectordb.search(query, limit=max(self.settings.RAG_CANDIDATES, top_k))
        except Exception as exc:
            raise KnowledgeBaseUnavailable(f"Vector search failed: {exc}") from exc

        candidates = [
            RetrievedChunk(
                text=p.payload.get("text") or p.payload.get("content", ""),
                document_name=p.payload.get("document_name", "Knowledge base"),
                section=p.payload.get("section", ""),
                source=p.payload.get("source", ""),
                chunk_id=p.payload.get("chunk_id", str(p.id)),
                score=float(p.score),
            )
            for p in points
        ]
        if not candidates:
            return []

        if self.settings.RAG_RERANK:
            pairs = [(query, f"{c.document_name} - {c.section}\n{c.text}") for c in candidates]
            # ms-marco cross-encoder returns logits; squash to 0..1 for thresholding.
            logits = _get_reranker().predict(pairs)
            for chunk, logit in zip(candidates, logits):
                chunk.score = 1 / (1 + math.exp(-float(logit)))
            candidates.sort(key=lambda c: c.score, reverse=True)

        relevant = [c for c in candidates if c.score >= self.settings.RAG_MIN_SCORE][:top_k]

        log_event(
            "rag.retrieval",
            candidates=len(candidates),
            relevant=len(relevant),
            best_score=round(candidates[0].score, 3),
            sources=[c.chunk_id for c in relevant],
        )
        return relevant


_retriever: KnowledgeRetriever | None = None


def get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
    return _retriever


def warm_up() -> None:
    """Load the embedding and reranker models ahead of the first request."""
    from vectorizer.app.embeddings.embedding_generator import get_embedding_model

    get_embedding_model()
    if get_settings().RAG_RERANK:
        _get_reranker()
