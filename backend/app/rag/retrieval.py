"""Hybrid retrieval over the user's documents and the knowledge base.

Vector similarity (pgvector on PostgreSQL) and BM25 keyword scores are merged with
reciprocal rank fusion. A vector hit only counts above MIN_SIMILARITY, so unrelated
questions return nothing instead of the "least bad" chunk. Without a Gemini key the
search is keyword-only.

User-document search always filters on the caller's user_id.
"""

import logging
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, KnowledgeChunk, KnowledgeDocument
from app.services.llm_service import LLMError, get_llm

logger = logging.getLogger("travel.rag")

MIN_SIMILARITY = 0.6   # Gemini embeddings: relevant ~0.7+, unrelated ~0.4-0.5
CANDIDATES = 20
RRF_K = 60

_STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i if in is it its me my of on "
    "or our so than that the their them then there these this to was we what when where which "
    "who why will with you your".split()
)


@dataclass
class SearchResult:
    source_type: str          # "user_document" | "knowledge_base"
    text: str
    score: float
    title: str                # filename, or knowledge-base document title
    section: str | None
    page: int | None
    document_id: str | None   # user document id
    document_type: str | None
    source: str | None        # knowledge-base file path
    category: str | None


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def bm25(query: str, texts: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    terms = set(tokenize(query))
    docs = [tokenize(t) for t in texts]
    if not terms or not docs:
        return [0.0] * len(texts)
    avg_len = sum(len(d) for d in docs) / len(docs) or 1
    df = Counter(term for d in docs for term in set(d) if term in terms)
    scores = []
    for d in docs:
        tf = Counter(d)
        score = 0.0
        for term in terms:
            if tf[term]:
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                norm = k1 * (1 - b + b * len(d) / avg_len)
                score += idf * tf[term] * (k1 + 1) / (tf[term] + norm)
        scores.append(score)
    return scores


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))  # vectors are unit length


async def query_vector(query: str) -> list[float] | None:
    llm = get_llm()
    if not llm.configured:
        return None
    try:
        return (await llm.embed([query], query=True))[0]
    except LLMError as exc:
        logger.warning("query embedding failed; keyword search only", extra={"error": str(exc)})
        return None


async def _hybrid(session: AsyncSession, model, filters: list, query: str,
                  vector: list[float] | None) -> list[tuple[int, float]]:
    """(chunk id, fused score), best first."""
    rows = (await session.execute(select(model.id, model.text).where(*filters))).all()
    if not rows:
        return []

    ranked: dict[int, float] = {}
    keyword = sorted(zip([r.id for r in rows], bm25(query, [r.text for r in rows]),
                         strict=True), key=lambda x: -x[1])
    for rank, (chunk_id, score) in enumerate(keyword[:CANDIDATES]):
        if score > 0:
            ranked[chunk_id] = ranked.get(chunk_id, 0) + 1 / (RRF_K + rank)

    if vector is not None:
        if session.get_bind().dialect.name == "postgresql":
            distance = model.embedding.cosine_distance(vector)
            hits = (await session.execute(
                select(model.id, (1 - distance).label("sim"))
                .where(*filters, model.embedding.is_not(None))
                .order_by(distance).limit(CANDIDATES)
            )).all()
            similar = [(h.id, h.sim) for h in hits]
        else:  # SQLite (development/tests): compute in Python
            emb = (await session.execute(
                select(model.id, model.embedding).where(*filters, model.embedding.is_not(None))
            )).all()
            similar = sorted(((e.id, _cosine(vector, e.embedding)) for e in emb),
                             key=lambda x: -x[1])[:CANDIDATES]
        for rank, (chunk_id, sim) in enumerate(similar):
            if sim >= MIN_SIMILARITY:
                ranked[chunk_id] = ranked.get(chunk_id, 0) + 1 / (RRF_K + rank)

    return sorted(ranked.items(), key=lambda x: -x[1])


async def search_user_documents(session: AsyncSession, user_id: uuid.UUID, query: str,
                                limit: int = 5, vector: list[float] | None = None,
                                ) -> list[SearchResult]:
    if vector is None:
        vector = await query_vector(query)
    fused = await _hybrid(session, DocumentChunk, [DocumentChunk.user_id == user_id],
                          query, vector)
    ids = [chunk_id for chunk_id, _ in fused[:limit]]
    if not ids:
        return []
    rows = {r.DocumentChunk.id: r for r in (await session.execute(
        select(DocumentChunk, Document.filename, Document.document_type)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_(ids), DocumentChunk.user_id == user_id)
    )).all()}
    scores = dict(fused)
    return [
        SearchResult(
            source_type="user_document", text=rows[i].DocumentChunk.text,
            score=round(scores[i], 4), title=rows[i].filename, section=None,
            page=rows[i].DocumentChunk.page, document_id=str(rows[i].DocumentChunk.document_id),
            document_type=rows[i].document_type.value if rows[i].document_type else None,
            source=None, category=None,
        )
        for i in ids if i in rows
    ]


async def search_knowledge(session: AsyncSession, query: str, limit: int = 5,
                           vector: list[float] | None = None) -> list[SearchResult]:
    if vector is None:
        vector = await query_vector(query)
    fused = await _hybrid(session, KnowledgeChunk, [], query, vector)
    ids = [chunk_id for chunk_id, _ in fused[:limit]]
    if not ids:
        return []
    rows = {r.KnowledgeChunk.id: r for r in (await session.execute(
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
        .where(KnowledgeChunk.id.in_(ids))
    )).all()}
    scores = dict(fused)
    return [
        SearchResult(
            source_type="knowledge_base", text=rows[i].KnowledgeChunk.text,
            score=round(scores[i], 4), title=rows[i].KnowledgeDocument.title,
            section=rows[i].KnowledgeChunk.section, page=None, document_id=None,
            document_type=None, source=rows[i].KnowledgeDocument.source,
            category=rows[i].KnowledgeDocument.category,
        )
        for i in ids if i in rows
    ]
