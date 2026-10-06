from functools import lru_cache
from typing import Union, List

from vectorizer.app.core.logger import logger
from vectorizer.app.core.settings import get_settings


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load the local embedding model on first use (output dimension = 384)."""
    from sentence_transformers import SentenceTransformer

    model_name = get_settings().EMBEDDING_MODEL
    logger.info(f"Loading embedding model {model_name}")
    return SentenceTransformer(model_name)


def generate_embedding(
    content: Union[str, List[str]]
) -> Union[List[float], List[List[float]]]:

    if not isinstance(content, (str, list)):
        raise ValueError("Content must be either a string or a list of strings")

    try:
        embeddings = get_embedding_model().encode(
            content,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        raise
