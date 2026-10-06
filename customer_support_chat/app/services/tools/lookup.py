from typing import List, Dict, Tuple

from langchain_core.tools import tool

from customer_support_chat.app.core.logger import logger
from customer_support_chat.app.services.rag import KnowledgeBaseUnavailable, get_retriever

NO_ANSWER = (
    "NO_RELEVANT_POLICY_FOUND: The knowledge base contains no information that answers this "
    "question. Tell the customer you could not verify this in the official policies; do not "
    "guess or invent a policy."
)
UNAVAILABLE = (
    "KNOWLEDGE_BASE_UNAVAILABLE: Policy documents cannot be searched right now. Tell the customer "
    "you cannot verify policy details at the moment; do not guess or invent a policy."
)


def search_knowledge_base(query: str, limit: int | None = None) -> List[Dict]:
    """Return relevant knowledge-base chunks with their source metadata."""
    return [
        {**chunk.citation(), "text": chunk.text}
        for chunk in get_retriever().retrieve(query, top_k=limit)
    ]


@tool(response_format="content_and_artifact")
def lookup_policy(query: str) -> Tuple[str, List[Dict]]:
    """Search the official company policies and FAQs (baggage, check-in, cancellation, refunds,
    flight changes, fares, payment, travel documents, car rental, hotel and excursion policies).
    Use this for ANY policy or general-knowledge question, and before making flight changes or
    other 'write' operations. Do not use it for customer-specific booking data."""
    try:
        results = search_knowledge_base(query)
    except KnowledgeBaseUnavailable as exc:
        logger.error(f"Policy lookup unavailable: {exc}")
        return UNAVAILABLE, []

    if not results:
        return NO_ANSWER, []

    excerpts = "\n\n".join(
        f"[{i}] {r['document_name']} - {r['section']}\n{r['text']}"
        for i, r in enumerate(results, start=1)
    )
    content = (
        "Relevant policy excerpts. Answer ONLY from these excerpts and mention the document "
        "names you used. If they do not fully answer the question, say which part you could "
        f"not verify.\n\n{excerpts}"
    )
    sources = [{k: v for k, v in r.items() if k != "text"} for r in results]
    return content, sources
