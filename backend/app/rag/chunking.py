"""Split text into overlapping chunks, preferring paragraph and sentence boundaries."""

import re

CHUNK_SIZE = 900
OVERLAP = 150


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    # Pieces no longer than `size`: paragraphs, else sentences, else hard cuts.
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if len(para) <= size:
            pieces.append(para)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n", para):
            while len(sentence) > size:
                pieces.append(sentence[:size])
                sentence = sentence[size:]
            if sentence.strip():
                pieces.append(sentence.strip())

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current)
            # Start the next chunk with the tail of this one so context isn't cut.
            current = current[-overlap:].lstrip() if overlap else ""
        current = f"{current}\n{piece}" if current else piece
    if current.strip():
        chunks.append(current)
    return chunks
