#!/usr/bin/env bash
# Start all Karna services in the background:
# 1. Local llama-server on port 8001
# 2. FastAPI Health server on port 8000
# 3. Telegram Bot (long polling)
# Usage: ./scripts/start_all.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Starting Karna Services ==="

# 1. Start Local LLM Server if not running
if curl -s -o /dev/null http://127.0.0.1:8001/v1/models; then
  echo "[OK] llama-server is already running on http://127.0.0.1:8001"
else
  echo "Starting llama-server on port 8001..."
  nohup "$PROJECT_ROOT/scripts/start_llama.sh" > "$PROJECT_ROOT/llama.log" 2>&1 &
  sleep 3
fi

# 2. Start FastAPI Server if not running
if curl -s -o /dev/null http://127.0.0.1:8000/health; then
  echo "[OK] FastAPI server is already running on http://127.0.0.1:8000"
else
  echo "Starting FastAPI server on port 8000..."
  nohup "$PROJECT_ROOT/scripts/start.sh" > "$PROJECT_ROOT/api.log" 2>&1 &
  sleep 2
fi

# 3. Start Telegram Bot if not running
if pgrep -f "app.telegram_bot" > /dev/null; then
  echo "[OK] Telegram bot is already running"
else
  echo "Starting Telegram bot..."
  nohup "$PROJECT_ROOT/scripts/start_telegram.sh" > "$PROJECT_ROOT/telegram.log" 2>&1 &
  sleep 2
fi

echo
"$PROJECT_ROOT/scripts/health_check.sh"
