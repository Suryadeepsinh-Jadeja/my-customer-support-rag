"""Knowledge-base ingestion: load -> clean -> split by section -> chunk.

Documents are Markdown files under KNOWLEDGE_BASE_DIR. Each file starts with a
`# Title` line and may carry simple front matter lines directly below it:

    # Baggage Policy
    category: flights
    last_updated: 2026-09-01

Every `##` heading starts a new section; long sections are further split into
overlapping chunks. Each chunk keeps the metadata needed for citations.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from vectorizer.app.core.logger import logger

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120

_FRONT_MATTER = re.compile(r"^([a-z_]+):\s*(.+)$")


@dataclass
class KnowledgeChunk:
    text: str
    metadata: dict

    @property
    def embedding_text(self) -> str:
        # Prefixing title/section gives short chunks the context they need to be found.
        return f"{self.metadata['document_name']} - {self.metadata['section']}\n{self.text}"


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)          # stray HTML tags
    text = text.replace("\t", "    ")
    text = re.sub(r"[  ]+\n", "\n", text)     # trailing spaces
    text = re.sub(r"\n{3,}", "\n\n", text)         # excess blank lines
    return text.strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "section"


def parse_document(path: Path, root: Path) -> list[KnowledgeChunk]:
    raw = clean_text(path.read_text(encoding="utf-8"))
    lines = raw.splitlines()

    title = path.stem.replace("_", " ").title()
    meta: dict = {}
    body_start = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body_start = 1
        while body_start < len(lines):
            match = _FRONT_MATTER.match(lines[body_start].strip())
            if not match:
                break
            meta[match.group(1)] = match.group(2).strip()
            body_start += 1

    # Split into (section heading, section text)
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    for line in lines[body_start:]:
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    source = path.relative_to(root).as_posix()
    doc_id = _slug(path.stem)
    chunks: list[KnowledgeChunk] = []
    for section, section_lines in sections:
        section_text = "\n".join(section_lines).strip()
        if not section_text:
            continue
        for index, piece in enumerate(splitter.split_text(section_text)):
            piece = piece.strip()
            if len(piece) < 20:
                continue
            chunks.append(
                KnowledgeChunk(
                    text=piece,
                    metadata={
                        "type": "knowledge",
                        "source": source,
                        "document_id": doc_id,
                        "document_name": title,
                        "section": section,
                        "category": meta.get("category", "general"),
                        "last_updated": meta.get("last_updated", ""),
                        "chunk_index": index,
                        "chunk_id": f"{doc_id}#{_slug(section)}-{index}",
                        "text": piece,
                    },
                )
            )
    return chunks


def load_knowledge_chunks(directory: str) -> list[KnowledgeChunk]:
    root = Path(directory)
    if not root.is_dir():
        logger.warning(f"Knowledge base directory {root} does not exist")
        return []

    chunks: list[KnowledgeChunk] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        doc_chunks = parse_document(path, root)
        logger.info(f"Loaded {len(doc_chunks)} chunks from {path.name}")
        chunks.extend(doc_chunks)
    return chunks
