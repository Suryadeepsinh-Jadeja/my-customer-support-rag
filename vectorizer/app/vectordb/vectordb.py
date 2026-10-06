import sqlite3
import uuid

from qdrant_client.models import Distance, VectorParams, PointStruct
from tqdm import tqdm

from vectorizer.app.core.settings import get_settings
from vectorizer.app.core.logger import logger
from vectorizer.app.embeddings.embedding_generator import generate_embedding
from vectorizer.app.knowledge.loader import load_knowledge_chunks
from .chunkenizer import recursive_character_splitting
from .client import get_qdrant_client


settings = get_settings()

# Sentence Transformer produces 384-dimensional embeddings
EMBEDDING_DIMENSION = 384

# Number of chunks embedded and upserted per batch.
BATCH_SIZE = 256

# Deterministic point ids, so re-ingesting the same chunk overwrites it.
_POINT_NAMESPACE = uuid.UUID("6f1c1f9e-6c55-4a43-9a0e-4b7b0f2a9c11")


class VectorDB:

    def __init__(
        self,
        table_name=None,
        collection_name=None,
        create_collection=False,
    ):
        self.table_name = table_name
        self.collection_name = collection_name

        # Shared, lazily-created client (see client.py).
        self._client = None

        if create_collection:
            self.create_or_clear_collection()

    @property
    def client(self):
        if self._client is None:
            self._client = get_qdrant_client()
        return self._client

    # ---------------------------------------------------------
    # QDRANT COLLECTION
    # ---------------------------------------------------------

    def create_or_clear_collection(self):

        if self.client.collection_exists(self.collection_name):
            logger.info(
                f"Collection {self.collection_name} already exists. Recreating it."
            )
            self.client.delete_collection(collection_name=self.collection_name)

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )

        logger.info(
            f"Created collection {self.collection_name} "
            f"with dimension {EMBEDDING_DIMENSION}"
        )

    def collection_ready(self) -> bool:
        try:
            return self.client.collection_exists(self.collection_name) and (
                self.client.count(self.collection_name, exact=False).count > 0
            )
        except Exception as e:
            logger.error(f"Could not inspect collection {self.collection_name}: {e}")
            return False

    # ---------------------------------------------------------
    # FORMAT DATABASE CONTENT
    # ---------------------------------------------------------

    def format_content(self, data, collection_name):

        if collection_name == "car_rentals_collection":

            booking_status = "booked" if data["booked"] else "not booked"

            return (
                f"Car rental: {data['name']}, "
                f"located at: {data['location']}, "
                f"price tier: {data['price_tier']}. "
                f"Rental period starts on "
                f"{data['start_date']} and ends on "
                f"{data['end_date']}. "
                f"Currently, the rental is: "
                f"{booking_status}."
            )

        elif collection_name == "excursions_collection":

            booking_status = "booked" if data["booked"] else "not booked"

            return (
                f"Excursion: {data['name']} "
                f"at {data['location']}. "
                f"Additional details: "
                f"{data['details']}. "
                f"Currently, the excursion is "
                f"{booking_status}. "
                f"Keywords: {data['keywords']}."
            )

        elif collection_name == "flights_collection":

            return (
                f"Flight {data['flight_no']} "
                f"from {data['departure_airport']} "
                f"to {data['arrival_airport']} "
                f"was scheduled to depart at "
                f"{data['scheduled_departure']} "
                f"and arrive at "
                f"{data['scheduled_arrival']}. "
                f"The actual departure was at "
                f"{data['actual_departure']} "
                f"and the actual arrival was at "
                f"{data['actual_arrival']}. "
                f"Currently, the flight status is "
                f"'{data['status']}' and it was operated "
                f"with aircraft code "
                f"{data['aircraft_code']}."
            )

        elif collection_name == "hotels_collection":

            booking_status = "booked" if data["booked"] else "not booked"

            return (
                f"Hotel {data['name']} "
                f"located in {data['location']} "
                f"is categorized as "
                f"{data['price_tier']} tier. "
                f"The check-in date is "
                f"{data['checkin_date']} and the "
                f"check-out date is "
                f"{data['checkout_date']}. "
                f"Currently, the booked status is: "
                f"{booking_status}."
            )

        else:

            return str(data)

    # ---------------------------------------------------------
    # BATCHED EMBEDDING + UPSERT
    # ---------------------------------------------------------

    def _upsert_chunks(self, items, description):
        """items: list of (text_to_embed, payload, point_key)."""

        total = 0
        for start in tqdm(range(0, len(items), BATCH_SIZE), desc=description):
            batch = items[start:start + BATCH_SIZE]
            vectors = generate_embedding([text for text, _, _ in batch])

            points = []
            for (text, payload, key), vector in zip(batch, vectors):
                if len(vector) != EMBEDDING_DIMENSION:
                    raise ValueError(
                        f"Embedding dimension mismatch. Expected "
                        f"{EMBEDDING_DIMENSION}, got {len(vector)}"
                    )
                points.append(
                    PointStruct(
                        id=str(uuid.uuid5(_POINT_NAMESPACE, f"{self.collection_name}:{key}")),
                        vector=vector,
                        payload={"content": text, **payload},
                    )
                )

            self.client.upsert(collection_name=self.collection_name, points=points)
            total += len(points)

        logger.info(f"Indexed {total} chunks into {self.collection_name}")
        return total

    # ---------------------------------------------------------
    # CREATE EMBEDDINGS
    # ---------------------------------------------------------

    def create_embeddings(self):

        if self.table_name == "knowledge_base":
            return self.index_knowledge_base()
        return self.index_regular_docs()

    # ---------------------------------------------------------
    # NORMAL DATABASE TABLES
    # ---------------------------------------------------------

    def index_regular_docs(self):

        db_connection = sqlite3.connect(settings.SQLITE_DB_PATH)
        cursor = db_connection.cursor()
        cursor.execute(f"SELECT * FROM {self.table_name}")
        rows = cursor.fetchall()
        column_names = [column[0] for column in cursor.description]
        db_connection.close()

        if not rows:
            logger.warning(f"No data found in table {self.table_name}")
            return 0

        items = []
        for row_index, row in enumerate(rows):
            item = dict(zip(column_names, row))
            content = self.format_content(item, self.collection_name)
            for chunk_index, chunk in enumerate(recursive_character_splitting(content)):
                if chunk:
                    items.append((chunk, item, f"{row_index}:{chunk_index}"))

        if not items:
            logger.warning(f"No valid chunks generated for {self.collection_name}")
            return 0

        return self._upsert_chunks(items, f"Embedding {self.collection_name}")

    # ---------------------------------------------------------
    # KNOWLEDGE BASE (policies / FAQs)
    # ---------------------------------------------------------

    def index_knowledge_base(self):

        chunks = load_knowledge_chunks(settings.KNOWLEDGE_BASE_DIR)
        if not chunks:
            logger.warning(
                f"No knowledge base documents found in {settings.KNOWLEDGE_BASE_DIR}"
            )
            return 0

        items = [
            (chunk.embedding_text, chunk.metadata, chunk.metadata["chunk_id"])
            for chunk in chunks
        ]
        return self._upsert_chunks(items, "Embedding knowledge base")

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    def search(
        self,
        query,
        limit=3,
        with_payload=True,
    ):

        query_vector = generate_embedding(query)

        if len(query_vector) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"Query embedding dimension mismatch. "
                f"Expected {EMBEDDING_DIMENSION}, "
                f"got {len(query_vector)}"
            )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            with_payload=with_payload,
        )

        logger.debug(
            f"Vector search on {self.collection_name} returned "
            f"{len(response.points)} results."
        )

        return response.points
