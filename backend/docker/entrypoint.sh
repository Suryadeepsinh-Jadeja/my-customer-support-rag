#!/bin/sh
set -e

# Apply database migrations before starting, unless disabled (e.g. when a separate
# release job runs them).
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
