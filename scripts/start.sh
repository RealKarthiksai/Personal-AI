#!/usr/bin/env bash
# Start the Local AI Chatbot FastAPI service (uvicorn).
# Usage: ./scripts/start.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VENV="$PROJECT_ROOT/.venv"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -d "$VENV" ]; then
  echo "ERROR: Virtual environment not found at $VENV" >&2
  echo "Create it with: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  echo "Copy .env.example to .env and fill in your values first." >&2
  exit 1
fi

# Activate virtual environment.
# shellcheck source=/dev/null
. "$VENV/bin/activate"

# Ensure the database directory exists.
mkdir -p "$PROJECT_ROOT/data"

cd "$PROJECT_ROOT"

echo "Starting Local AI Chatbot API on http://127.0.0.1:8000"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000