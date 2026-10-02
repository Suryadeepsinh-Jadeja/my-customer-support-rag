import asyncio
import re
import sqlite3
import uuid

import aiohttp
from more_itertools import chunked
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from tqdm.asyncio import tqdm_asyncio

from vectorizer.app.core.settings import get_settings
from vectorizer.app.core.logger import logger
from vectorizer.app.embeddings.embedding_generator import generate_embedding
from .chunkenizer import recursive_character_splitting


settings = get_settings()

# Sentence Transformer produces 384-dimensional embeddings
EMBEDDING_DIMENSION = 384


class VectorDB:

    def __init__(
        self,
        table_name=None,
        collection_name=None,
        create_collection=False,
    ):
        self.table_name = table_name
        self.collection_name = collection_name

        self.client = QdrantClient(
            url=settings.QDRANT_URL
        )

        logger.info(
            f"Connected to Qdrant: {self.collection_name}"
        )

        if create_collection:
            self.create_or_clear_collection()

    # ---------------------------------------------------------
    # QDRANT COLLECTION
    # ---------------------------------------------------------

    def create_or_clear_collection(self):

        if self.client.collection_exists(
            self.collection_name
        ):
            logger.info(
                f"Collection {self.collection_name} already exists. "
                f"Recreating it."
            )

            self.client.delete_collection(
                collection_name=self.collection_name
            )

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

    # ---------------------------------------------------------
    # FORMAT DATABASE CONTENT
    # ---------------------------------------------------------

    def format_content(self, data, collection_name):

        if collection_name == "car_rentals_collection":

            booking_status = (
                "booked"
                if data["booked"]
                else "not booked"
            )

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

            booking_status = (
                "booked"
                if data["booked"]
                else "not booked"
            )

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

            booking_status = (
                "booked"
                if data["booked"]
                else "not booked"
            )

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

        elif collection_name == "faq_collection":

            return data["page_content"]

        else:

            return str(data)

    # ---------------------------------------------------------
    # EMBEDDING
    # ---------------------------------------------------------

    async def generate_embedding_async(
        self,
        content,
        session=None,
    ):

        try:

            embedding = generate_embedding(content)

            if len(embedding) != EMBEDDING_DIMENSION:

                raise ValueError(
                    f"Embedding dimension mismatch. "
                    f"Expected {EMBEDDING_DIMENSION}, "
                    f"got {len(embedding)}"
                )

            return embedding

        except Exception as e:

            logger.error(
                f"Embedding generation failed: {str(e)}"
            )

            raise

    # ---------------------------------------------------------
    # PROCESS CHUNK
    # ---------------------------------------------------------

    async def process_chunk(
        self,
        chunk,
        metadata,
        session,
    ):

        embedding = await self.generate_embedding_async(
            chunk,
            session,
        )

        return PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "content": chunk,
                **metadata,
            },
        )

    # ---------------------------------------------------------
    # CREATE EMBEDDINGS
    # ---------------------------------------------------------

    async def create_embeddings_async(self):

        if self.table_name == "faq":

            await self.index_faq_docs()

        else:

            await self.index_regular_docs()

    # ---------------------------------------------------------
    # NORMAL DATABASE TABLES
    # ---------------------------------------------------------

    async def index_regular_docs(self):

        db_connection = sqlite3.connect(
            settings.SQLITE_DB_PATH
        )

        cursor = db_connection.cursor()

        cursor.execute(
            f"SELECT * FROM {self.table_name}"
        )

        rows = cursor.fetchall()

        column_names = [
            column[0]
            for column in cursor.description
        ]

        db_connection.close()

        if not rows:

            logger.warning(
                f"No data found in table "
                f"{self.table_name}"
            )

            return

        data = [
            dict(zip(column_names, row))
            for row in rows
        ]

        formatted_chunks = []

        for item in data:

            content = self.format_content(
                item,
                self.collection_name,
            )

            chunks = recursive_character_splitting(
                content
            )

            for chunk in chunks:

                if chunk:

                    formatted_chunks.append(
                        (chunk, item)
                    )

        if not formatted_chunks:

            logger.warning(
                f"No valid chunks generated for "
                f"{self.collection_name}"
            )

            return

        # Keep this relatively small because the
        # Sentence Transformer runs locally.
        batch_size = 10

        async with aiohttp.ClientSession() as session:

            for start in range(
                0,
                len(formatted_chunks),
                batch_size,
            ):

                batch = formatted_chunks[
                    start:start + batch_size
                ]

                tasks = []

                for chunk, metadata in batch:

                    tasks.append(
                        self.process_chunk(
                            chunk,
                            metadata,
                            session,
                        )
                    )

                points = []

                for task in tqdm_asyncio.as_completed(
                    tasks,
                    desc=(
                        f"Generating embeddings for "
                        f"{self.collection_name} "
                        f"(batch "
                        f"{start // batch_size + 1})"
                    ),
                    total=len(tasks),
                ):

                    try:

                        point = await task

                        if point is not None:

                            points.append(point)

                    except Exception as e:

                        logger.error(
                            f"Error processing chunk: "
                            f"{str(e)}"
                        )

                if points:

                    self.client.upsert(
                        collection_name=self.collection_name,
                        points=points,
                    )

                    logger.info(
                        f"Indexed {len(points)} documents "
                        f"into {self.collection_name}"
                    )

        logger.info(
            f"Finished indexing "
            f"{self.collection_name}. "
            f"Total chunks: "
            f"{len(formatted_chunks)}"
        )

    # ---------------------------------------------------------
    # FAQ
    # ---------------------------------------------------------

    async def index_faq_docs(self):

        faq_url = (
            "https://storage.googleapis.com/"
            "benchmarks-artifacts/travel-db/"
            "swiss_faq.md"
        )

        async with aiohttp.ClientSession() as session:

            async with session.get(
                faq_url
            ) as response:

                faq_text = await response.text()

        docs = [
            {
                "page_content": txt.strip()
            }
            for txt in re.split(
                r"(?=\n##)",
                faq_text
            )
            if txt.strip()
        ]

        async with aiohttp.ClientSession() as session:

            tasks = [
                self.process_chunk(
                    doc["page_content"],
                    {"type": "faq"},
                    session,
                )
                for doc in docs
            ]

            points = await tqdm_asyncio.gather(
                *tasks,
                desc="Generating embeddings for FAQ documents",
            )

        if points:

            for batch in chunked(
                points,
                10,
            ):

                self.client.upsert(
                    collection_name=self.collection_name,
                    points=list(batch),
                )

            logger.info(
                f"Indexed {len(points)} FAQ documents "
                f"into {self.collection_name}"
            )

        else:

            logger.warning(
                "No FAQ documents were successfully "
                "embedded and indexed."
            )

    # ---------------------------------------------------------
    # PUBLIC CREATE EMBEDDINGS
    # ---------------------------------------------------------

    def create_embeddings(self):

        asyncio.run(
            self.create_embeddings_async()
        )

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    def search(
        self,
        query,
        limit=3,
        with_payload=True,
    ):

        query_vector = generate_embedding(
            query
        )

        if len(query_vector) != EMBEDDING_DIMENSION:

            raise ValueError(
                f"Query embedding dimension mismatch. "
                f"Expected {EMBEDDING_DIMENSION}, "
                f"got {len(query_vector)}"
            )

        logger.debug(
            f"Searching Qdrant with embedding "
            f"dimension: {len(query_vector)}"
        )

        search_result = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            with_payload=with_payload,
        )

        logger.info(
            f"Vector search completed successfully. "
            f"Found {len(search_result)} results."
        )

        return search_result


if __name__ == "__main__":

    vectordb = VectorDB(
        table_name="example_table",
        collection_name="example_collection",
        create_collection=True,
    )

    vectordb.create_embeddings()