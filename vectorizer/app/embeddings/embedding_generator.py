from typing import Union, List
from sentence_transformers import SentenceTransformer

from vectorizer.app.core.logger import logger


# Local embedding model
# Output dimension = 384
model = SentenceTransformer("all-MiniLM-L6-v2")


def generate_embedding(
    content: Union[str, List[str]]
) -> Union[List[float], List[List[float]]]:

    try:
        if isinstance(content, str):

            embedding = model.encode(
                content,
                normalize_embeddings=True
            )

            return embedding.tolist()

        elif isinstance(content, list):

            embeddings = model.encode(
                content,
                normalize_embeddings=True
            )

            return embeddings.tolist()

        else:
            raise ValueError(
                "Content must be either a string or a list of strings"
            )

    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        raise