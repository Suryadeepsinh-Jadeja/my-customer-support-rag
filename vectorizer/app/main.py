import argparse

from vectorizer.app.core.logger import logger
from vectorizer.app.vectordb.vectordb import VectorDB
from vectorizer.app.vectordb.client import close_qdrant_client

# (source, collection). "knowledge_base" is the policy/FAQ document store used
# for RAG; the others are travel-database tables used by the search tools.
COLLECTIONS = [
    ("knowledge_base", "knowledge_base_collection"),
    ("car_rentals", "car_rentals_collection"),
    ("trip_recommendations", "excursions_collection"),
    ("hotels", "hotels_collection"),
    ("flights", "flights_collection"),
]


def create_collections(only: list[str] | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    failures = []

    for table_name, collection_name in COLLECTIONS:
        if only and table_name not in only:
            continue
        try:
            logger.info(f"Indexing {table_name} -> {collection_name}")
            vectordb = VectorDB(
                table_name=table_name,
                collection_name=collection_name,
                create_collection=True,
            )
            results[collection_name] = vectordb.create_embeddings()
        except Exception:
            logger.exception(f"Failed to index {table_name}")
            failures.append(table_name)

    close_qdrant_client()

    if failures:
        raise RuntimeError(f"Indexing failed for: {', '.join(failures)}")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Qdrant collections.")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[name for name, _ in COLLECTIONS],
        help="Only (re)build these collections, e.g. --only knowledge_base",
    )
    args = parser.parse_args(argv)
    for collection, count in create_collections(args.only).items():
        print(f"{collection}: {count} chunks")


if __name__ == "__main__":
    main()
