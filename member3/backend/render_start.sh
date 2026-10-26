#!/usr/bin/env bash
# Start command of the hosted (Render) backend: brings the schema up to date,
# seeds the demo data once into an empty database (SEED_DEMO_DATA=1), then
# serves the API on Render's $PORT.
set -euo pipefail
cd "$(dirname "$0")"

alembic upgrade head

if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    python seed_if_empty.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
