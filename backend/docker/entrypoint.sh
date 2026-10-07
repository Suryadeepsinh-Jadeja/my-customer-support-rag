#!/bin/sh
set -e

# Apply database migrations and load the knowledge base before starting, unless disabled
# (e.g. for the worker, or when a separate release job does it).
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
    if [ -d /app/knowledge_base ]; then
        python -m app.rag.ingest /app/knowledge_base || echo "Knowledge base ingestion failed; continuing"
    fi
fi

exec "$@"
