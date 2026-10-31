#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DB_NAME="${E2E_DB_NAME:-zhongyi_e2e}"
PORT="${E2E_PORT:-8000}"
export DATABASE_URL="${E2E_DATABASE_URL:-postgresql+psycopg://linziwang@localhost:5432/${DB_NAME}}"
createdb "$DB_NAME" 2>/dev/null || true
.venv/bin/python scripts/e2e_bootstrap.py
exec .venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port "$PORT"
