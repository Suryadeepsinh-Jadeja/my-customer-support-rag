from os import environ
from dotenv import load_dotenv


load_dotenv()

class Config:
    SQLITE_DB_PATH: str = environ.get("SQLITE_DB_PATH", "./customer_support_chat/data/travel2.sqlite")
    KNOWLEDGE_BASE_DIR: str = environ.get("KNOWLEDGE_BASE_DIR", "./knowledge_base")

    # QDRANT_URL (server mode) takes precedence over QDRANT_PATH (embedded mode).
    QDRANT_URL: str = environ.get("QDRANT_URL", "").strip()
    QDRANT_API_KEY: str = environ.get("QDRANT_API_KEY", "").strip()
    QDRANT_PATH: str = environ.get("QDRANT_PATH", "./customer_support_chat/data/qdrant_local")

    EMBEDDING_MODEL: str = environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    RERANKER_MODEL: str = environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

def get_settings():
    return Config()
