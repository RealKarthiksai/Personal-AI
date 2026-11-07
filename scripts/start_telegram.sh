#!/usr/bin/env bash
# Start the Karna Telegram AI Chatbot.
# Usage: ./scripts/start_telegram.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VENV="$PROJECT_ROOT/.venv"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -d "$VENV" ]; then
  echo "ERROR: Virtual environment not found at $VENV" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

. "$VENV/bin/activate"
mkdir -p "$PROJECT_ROOT/data"
cd "$PROJECT_ROOT"

echo "Starting Karna Telegram AI Chatbot (long polling)..."
exec python -m app.telegram_bot
