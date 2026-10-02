# customer_support_chat/app/services/vectordb/vectordb.py

import uuid

from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct,
)

from customer_support_chat.app.services.utils import get_qdrant_client
from customer_support_chat.app.services.vectordb.chunkenizer import (
    recursive_character_splitting,
)
from customer_support_chat.app.core.logger import logger

# Shared embedding function
from vectorizer.app.embeddings.embedding_generator import generate_embedding


# IMPORTANT:
# sentence-transformers model currently returns 384-dimensional vectors.
EMBEDDING_DIMENSION = 384


class VectorDB:
    def __init__(self, collection_name):
        self.collection_name = collection_name
        self.client = get_qdrant_client()

        self.create_collection()

    def create_collection(self):
        """
        Create the Qdrant collection if it does not already exist.

        The current sentence-transformers embedding model returns
        384-dimensional vectors, so Qdrant must also use size=384.
        """

        try:
            exists = self.client.collection_exists(
                collection_name=self.collection_name
            )

            if not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIMENSION,
                        distance=Distance.COSINE,
                    ),
                )

                logger.info(
                    f"Created new collection: {self.collection_name} "
                    f"with dimension {EMBEDDING_DIMENSION}"
                )

            else:
                logger.info(
                    f"Collection {self.collection_name} already exists"
                )

        except Exception as e:
            logger.error(
                f"Failed to create/check collection "
                f"{self.collection_name}: {str(e)}"
            )
            raise

    def generate_embedding(self, content):
        """
        Generate an embedding using the shared
        sentence-transformers embedding function.
        """

        try:
            embedding = generate_embedding(content)

            dimension = len(embedding)

            logger.debug(
                f"Generated embedding with dimension: {dimension}"
            )

            # Safety check
            if dimension != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"Embedding dimension mismatch. "
                    f"Expected {EMBEDDING_DIMENSION}, "
                    f"but got {dimension}."
                )

            return embedding

        except Exception as e:
            logger.error(
                f"Failed to generate embedding: {str(e)}"
            )
            raise

    def upsert_vector(
        self,
        doc_id,
        chunk_text,
        embedding,
        url,
        chunk_index,
    ):
        """
        Store one document chunk and its embedding in Qdrant.
        """

        chunk_id = str(uuid.uuid4())

        payload = {
            "url": url,
            "document_id": str(doc_id),
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
        }

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=chunk_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

    def create_embeddings(self, docs):
        """
        Split documents into chunks, generate embeddings,
        and store them in Qdrant.

        Expected docs format:

        [
            (doc_id, content, url),
            ...
        ]
        """

        for doc_id, content, url in docs:

            if content is None:
                logger.warning(
                    f"Skipping doc_id {doc_id} because content is None"
                )
                continue

            chunks = recursive_character_splitting(content)

            for i, chunk in enumerate(chunks):

                if not chunk or not chunk.strip():
                    continue

                try:
                    logger.info(
                        f"Generating embedding for "
                        f"doc_id: {doc_id}, "
                        f"chunk: {i + 1}/{len(chunks)}"
                    )

                    embedding = self.generate_embedding(chunk)

                    self.upsert_vector(
                        doc_id=doc_id,
                        chunk_text=chunk,
                        embedding=embedding,
                        url=url,
                        chunk_index=i,
                    )

                except Exception as e:

                    logger.error(
                        f"Failed to generate or store embedding "
                        f"for doc_id: {doc_id}, "
                        f"chunk: {i + 1}, "
                        f"error: {str(e)}"
                    )

        logger.info(
            "Completed generating embeddings for all documents"
        )

    def search(self, query, k=3):
        """
        Generate an embedding for the user query and
        perform similarity search in Qdrant.
        """

        try:
            query_embedding = self.generate_embedding(query)

            logger.debug(
                f"Searching Qdrant with embedding dimension: "
                f"{len(query_embedding)}"
            )

            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=k,
                with_payload=True,
            )

            logger.info(
                f"Vector search completed successfully. "
                f"Found {len(search_result)} results."
            )

            return search_result

        except Exception as e:

            logger.error(
                f"Vector search failed: {str(e)}"
            )

            raise