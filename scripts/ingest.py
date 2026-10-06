"""Offline ingestion: prepare the travel database and build the vector index.

    python scripts/ingest.py                         # everything
    python scripts/ingest.py --only knowledge_base   # after editing knowledge_base/*.md

Run this before starting the API, and re-run it whenever documents change.
With embedded Qdrant (QDRANT_PATH), stop the API first: only one process can
open the vector store at a time.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

os.chdir(ROOT)

from customer_support_chat.app.services.utils import download_and_prepare_db  # noqa: E402
from vectorizer.app.main import main as build_collections  # noqa: E402


if __name__ == "__main__":
    download_and_prepare_db()
    build_collections(sys.argv[1:])
