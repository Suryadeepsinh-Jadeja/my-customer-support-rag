"""Load the policy/FAQ knowledge base (Markdown) into the database.

    python -m app.rag.ingest ../knowledge_base

Re-runnable: unchanged files are skipped, changed files are re-chunked, deleted files are
removed. Files ingested without a Gemini key get embedded on the next run with a key.

File format: "# Title", optional "key: value" lines (category, last_updated), then
"## Section" headings.
"""

import asyncio
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import dispose_engine, get_sessionmaker
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.rag.chunking import chunk_text
from app.services.llm_service import get_llm

logger = logging.getLogger("travel.ingest")


@dataclass
class ParsedDoc:
    title: str
    meta: dict[str, str]
    sections: list[tuple[str, str]]  # (heading, body)


def parse_markdown(text: str, fallback_title: str) -> ParsedDoc:
    title, meta = fallback_title, {}
    sections: list[tuple[str, str]] = []
    heading, body = "Overview", list[str]()
    in_header = True
    for line in text.splitlines():
        if line.startswith("# ") and title == fallback_title and not sections and not body:
            title = line[2:].strip()
            continue
        if in_header and (m := re.match(r"^([a-z_]+):\s*(.+)$", line.strip())):
            meta[m[1]] = m[2].strip()
            continue
        if line.startswith("## "):
            in_header = False
            if "".join(body).strip():
                sections.append((heading, "\n".join(body).strip()))
            heading, body = line[3:].strip(), []
            continue
        if line.strip():
            in_header = False
        body.append(line)
    if "".join(body).strip():
        sections.append((heading, "\n".join(body).strip()))
    return ParsedDoc(title, meta, sections)


async def ingest_file(session: AsyncSession, root: Path, path: Path) -> str:
    """Returns "skipped", "added" or "updated"."""
    raw = path.read_text(encoding="utf-8")
    source = path.relative_to(root).as_posix()
    content_hash = hashlib.sha256(raw.encode()).hexdigest()
    llm = get_llm()

    existing = (await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.source == source)
    )).scalar_one_or_none()
    if existing and existing.content_hash == content_hash:
        missing_vectors = (await session.execute(
            select(KnowledgeChunk.id).where(KnowledgeChunk.knowledge_document_id == existing.id,
                                            KnowledgeChunk.embedding.is_(None)).limit(1)
        )).first()
        if not (missing_vectors and llm.configured):
            return "skipped"

    parsed = parse_markdown(raw, path.stem.replace("_", " ").title())
    # The section heading is kept in the chunk: it helps both search and the model.
    chunks = [(heading, f"{heading}\n{piece}") for heading, body in parsed.sections
              for piece in chunk_text(body)]
    vectors = None
    if llm.configured and chunks:
        vectors = await llm.embed([f"{parsed.title}: {t}" for _, t in chunks])

    status = "updated" if existing else "added"
    if existing is None:
        existing = KnowledgeDocument(source=source)
        session.add(existing)
    existing.title = parsed.title
    existing.category = parsed.meta.get("category") or path.parent.name
    existing.last_updated = parsed.meta.get("last_updated")
    existing.content_hash = content_hash
    await session.flush()
    await session.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == existing.id)
    )
    session.add_all(
        KnowledgeChunk(knowledge_document_id=existing.id, chunk_index=i, section=heading[:300],
                       text=text, embedding=vectors[i] if vectors else None)
        for i, (heading, text) in enumerate(chunks)
    )
    return status


async def ingest(root: Path) -> dict[str, int]:
    files = sorted(p for p in root.rglob("*.md") if p.name.lower() != "readme.md")
    counts = {"added": 0, "updated": 0, "skipped": 0, "removed": 0}
    async with get_sessionmaker()() as session:
        for path in files:
            counts[await ingest_file(session, root, path)] += 1
            await session.commit()
        sources = {p.relative_to(root).as_posix() for p in files}
        stale = (await session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.source.not_in(sources))
        )).scalars().all()
        for doc in stale:
            await session.delete(doc)
        counts["removed"] = len(stale)
        await session.commit()
    return counts


async def main(argv: list[str]) -> int:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.log_format)
    root = Path(argv[0] if argv else "../knowledge_base").resolve()
    if not root.is_dir():
        print(f"Knowledge base folder not found: {root}", file=sys.stderr)
        return 1
    if not get_llm().configured:
        print("GEMINI_API_KEY is not set: ingesting without embeddings (keyword search only).")
    try:
        counts = await ingest(root)
    finally:
        await dispose_engine()
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
