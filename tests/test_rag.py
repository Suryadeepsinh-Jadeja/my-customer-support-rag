"""RAG pipeline tests against the real knowledge base (embedded Qdrant + local models)."""

from pathlib import Path

from customer_support_chat.app.services.tools.lookup import lookup_policy
from vectorizer.app.knowledge.loader import clean_text, load_knowledge_chunks, parse_document


def _call(query):
    msg = lookup_policy.invoke(
        {"type": "tool_call", "name": "lookup_policy", "args": {"query": query}, "id": "t1"}
    )
    return msg.content, msg.artifact


# ---------------------------------------------------------------- ingestion


def test_loader_splits_sections_with_metadata(tmp_path: Path):
    doc = tmp_path / "pets.md"
    doc.write_text(
        "# Pet Policy\ncategory: flights\nlast_updated: 2026-01-01\n\n"
        "## Cabin\nSmall dogs up to 8 kg may travel in the cabin.\n\n"
        "## Hold\nLarger animals travel in the cargo hold.\n",
        encoding="utf-8",
    )
    chunks = parse_document(doc, tmp_path)
    assert [c.metadata["section"] for c in chunks] == ["Cabin", "Hold"]
    meta = chunks[0].metadata
    assert meta["document_name"] == "Pet Policy"
    assert meta["category"] == "flights"
    assert meta["source"] == "pets.md"
    assert meta["chunk_id"] == "pets#cabin-0"
    assert chunks[0].embedding_text.startswith("Pet Policy - Cabin")


def test_clean_text_strips_html_and_blank_lines():
    assert clean_text("<b>Hello</b>\n\n\n\nworld  \n") == "Hello\n\nworld"


def test_knowledge_base_excludes_untrusted_phone_number_section():
    chunks = load_knowledge_chunks("knowledge_base")
    assert len(chunks) > 50
    assert all("877-5O7-7341" not in c.text and "877-507-7341" not in c.text for c in chunks)
    assert not any(c.metadata["source"].lower() == "readme.md" for c in chunks)


# ---------------------------------------------------------------- retrieval


def test_known_question_returns_relevant_policy(vector_store):
    content, sources = _call("How many checked bags are included in Economy?")
    assert "Baggage Policy" in content
    assert "23 kg" in content
    assert sources[0]["document_name"] == "Baggage Policy"


def test_sources_have_citation_metadata(vector_store):
    _, sources = _call("When does online check-in open?")
    assert sources
    for source in sources:
        assert set(source) == {"document_name", "section", "source", "chunk_id", "score"}
        assert source["source"].endswith(".md")
        assert 0 <= source["score"] <= 1


def test_unknown_question_returns_no_answer_marker(vector_store):
    content, sources = _call("Do you allow emotional support peacocks on board?")
    assert content.startswith("NO_RELEVANT_POLICY_FOUND")
    assert sources == []


def test_irrelevant_question_returns_nothing(vector_store):
    content, sources = _call("Who won the football world cup?")
    assert content.startswith("NO_RELEVANT_POLICY_FOUND")
    assert sources == []


def test_domain_routing_hotel_vs_flight_cancellation(vector_store):
    _, sources = _call("What is the hotel cancellation policy?")
    assert sources[0]["document_name"] == "Hotel Booking Policy"


def test_missing_index_degrades_gracefully(vector_store, monkeypatch):
    from customer_support_chat.app.services import rag

    monkeypatch.setattr(rag.get_retriever().vectordb, "collection_name", "does_not_exist")
    monkeypatch.setattr(rag.get_retriever(), "_checked", False)
    content, sources = _call("baggage")
    assert content.startswith("KNOWLEDGE_BASE_UNAVAILABLE")
    assert sources == []
