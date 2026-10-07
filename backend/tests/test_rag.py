"""Chunking, knowledge-base ingestion and hybrid retrieval (with a fake embedder)."""

import hashlib
import math
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import DocumentChunk, KnowledgeChunk, KnowledgeDocument
from app.rag.chunking import chunk_text
from app.rag.ingest import ingest, parse_markdown
from app.rag.retrieval import search_knowledge, tokenize
from app.services import jobs
from app.services.llm_service import LLMService
from tests import samples
from tests.conftest import bearer, register

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


def fake_vector(text: str) -> list[float]:
    """Hashed bag of words: texts sharing words get a high cosine similarity."""
    v = [0.0] * 768
    for token in tokenize(text):
        v[int(hashlib.md5(token.encode()).hexdigest(), 16) % 768] += 1.0  # noqa: S324
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


@pytest.fixture
def fake_embeddings(monkeypatch):
    calls = []

    async def embed(self, texts, *, query=False):
        calls.append((len(texts), query))
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(LLMService, "configured", property(lambda self: True))
    monkeypatch.setattr(LLMService, "embed", embed)
    return calls


@pytest.fixture
def kb_copy(tmp_path):
    target = tmp_path / "kb"
    shutil.copytree(KB_DIR, target)
    return target


# ---------------------------------------------------------------- chunking


def test_short_text_is_one_chunk():
    assert chunk_text("Seat 12C, gate B34.") == ["Seat 12C, gate B34."]
    assert chunk_text("   ") == []


def test_long_text_is_split_with_overlap():
    paragraphs = [f"Paragraph {i}. " + "word " * 60 for i in range(10)]
    chunks = chunk_text("\n\n".join(paragraphs), size=500, overlap=80)
    assert len(chunks) > 3
    assert all(len(c) <= 500 + 80 + 1 for c in chunks)
    # Consecutive chunks share some text so nothing is lost at the boundary.
    assert chunks[0][-40:].strip() in chunks[1]
    joined = " ".join(chunks)
    assert all(f"Paragraph {i}." in joined for i in range(10))


def test_parse_markdown():
    doc = parse_markdown(
        "# Baggage Policy\ncategory: flights\nlast_updated: 2026-09-01\n\n"
        "## Hand baggage\nOne bag.\n\n## Checked\nTwo bags.\n", "fallback")
    assert doc.title == "Baggage Policy"
    assert doc.meta == {"category": "flights", "last_updated": "2026-09-01"}
    assert doc.sections == [("Hand baggage", "One bag."), ("Checked", "Two bags.")]


# --------------------------------------------------------------- ingestion


async def test_ingest_is_repeatable(kb_copy, db_session, fake_embeddings):
    first = await ingest(kb_copy)
    files = len([p for p in kb_copy.rglob("*.md") if p.name.lower() != "readme.md"])
    assert first == {"added": files, "updated": 0, "skipped": 0, "removed": 0}
    chunks = (await db_session.execute(select(func.count()).select_from(KnowledgeChunk))).scalar()
    assert chunks >= files

    assert await ingest(kb_copy) == {"added": 0, "updated": 0, "skipped": files, "removed": 0}

    baggage = kb_copy / "flights" / "baggage_policy.md"
    extra = "\n## Zebra transport\nZebras fly as cargo.\n"
    baggage.write_text(baggage.read_text(encoding="utf-8") + extra, encoding="utf-8")
    (kb_copy / "hotels" / "hotel_policy.md").unlink()
    result = await ingest(kb_copy)
    assert result["updated"] == 1 and result["removed"] == 1
    # No duplicate chunks after an update.
    sections = (await db_session.execute(select(KnowledgeChunk.section))).scalars().all()
    assert sections.count("Zebra transport") == 1

    doc = (await db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.source == "flights/baggage_policy.md")
    )).scalar_one()
    assert doc.title == "Baggage Policy" and doc.category == "flights"
    assert doc.last_updated == "2026-09-01"


async def test_ingest_without_key_then_embeds_later(kb_copy, db_session, monkeypatch):
    await ingest(kb_copy)  # GEMINI_API_KEY is empty in tests
    missing = select(func.count()).select_from(KnowledgeChunk).where(
        KnowledgeChunk.embedding.is_(None))
    assert (await db_session.execute(missing)).scalar() > 0

    async def embed(self, texts, *, query=False):
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(LLMService, "configured", property(lambda self: True))
    monkeypatch.setattr(LLMService, "embed", embed)
    result = await ingest(kb_copy)
    assert result["updated"] > 0
    assert (await db_session.execute(missing)).scalar() == 0


# --------------------------------------------------------------- retrieval


@pytest.mark.parametrize("with_vectors", [False, True])
async def test_knowledge_search(kb_copy, db_session, monkeypatch, with_vectors):
    if with_vectors:
        async def embed(self, texts, *, query=False):
            return [fake_vector(t) for t in texts]

        monkeypatch.setattr(LLMService, "configured", property(lambda self: True))
        monkeypatch.setattr(LLMService, "embed", embed)
    await ingest(kb_copy)

    hits = await search_knowledge(db_session, "What is the checked baggage allowance?", limit=3)
    assert hits, "expected a baggage policy hit"
    top = hits[0]
    assert top.source == "flights/baggage_policy.md"
    assert "baggage" in top.section.lower()
    assert top.source_type == "knowledge_base" and top.category == "flights"

    assert await search_knowledge(db_session, "quantum chromodynamics lecture notes") == []


async def test_document_is_indexed_and_searchable_only_by_its_owner(
        client, user_token, db_session, fake_embeddings):
    upload = await client.post("/api/documents", headers=bearer(user_token), files={
        "file": ("ticket.pdf", samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT), "application/pdf")})
    doc_id = upload.json()["id"]
    await jobs.run_pending()

    detail = (await client.get(f"/api/documents/{doc_id}", headers=bearer(user_token))).json()
    assert detail["status"] == "ready" and detail["steps"]["indexed"] is True
    chunk = (await db_session.execute(select(DocumentChunk))).scalar_one()
    assert chunk.embedding is not None and chunk.page == 1

    hits = (await client.post("/api/search", headers=bearer(user_token), json={
        "query": "which seat do I have on flight LX154", "scope": "documents"})).json()
    assert hits[0]["source_type"] == "user_document"
    assert hits[0]["document_id"] == doc_id and hits[0]["title"] == "ticket.pdf"
    assert hits[0]["page"] == 1 and "34A" in hits[0]["text"]

    other = (await register(client, email="eve@example.com", name="Eve")).json()["access_token"]
    client.cookies.clear()
    other_hits = (await client.post("/api/search", headers=bearer(other), json={
        "query": "which seat do I have on flight LX154", "scope": "documents"})).json()
    assert other_hits == []

    # Deleting the document deletes its chunks (no orphaned embeddings).
    await client.delete(f"/api/documents/{doc_id}", headers=bearer(user_token))
    assert (await db_session.execute(select(func.count()).select_from(DocumentChunk))).scalar() == 0


async def test_search_requires_auth(client):
    response = await client.post("/api/search", json={"query": "baggage"})
    assert response.status_code == 401
