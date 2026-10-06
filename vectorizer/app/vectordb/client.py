import atexit
import os
import threading

from qdrant_client import QdrantClient

from vectorizer.app.core.logger import logger
from vectorizer.app.core.settings import get_settings

_client: QdrantClient | None = None
_lock = threading.Lock()


def get_qdrant_client() -> QdrantClient:
    """Return the process-wide Qdrant client.

    Embedded (path) mode locks its storage folder, so every VectorDB in the
    process must share a single client instead of opening their own.
    """
    global _client
    with _lock:
        if _client is None:
            settings = get_settings()
            if settings.QDRANT_URL:
                _client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY or None,
                    timeout=10,
                )
                logger.info(f"Using Qdrant server at {settings.QDRANT_URL}")
            else:
                os.makedirs(settings.QDRANT_PATH, exist_ok=True)
                _client = QdrantClient(path=settings.QDRANT_PATH)
                logger.info(f"Using embedded Qdrant storage at {settings.QDRANT_PATH}")
        return _client


def close_qdrant_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


# Close cleanly before interpreter teardown (releases the embedded storage lock).
atexit.register(close_qdrant_client)
