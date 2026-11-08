#!/usr/bin/env bash
# Stop Karna services (uvicorn, telegram bot, llama-server).
# Usage: ./scripts/stop.sh [all|api|bot|llama]
set -euo pipefail

TARGET="${1:-all}"

stop_api() {
  if pkill -f "uvicorn app.main:app" 2>/dev/null; then
    echo "Stopped FastAPI service."
  else
    echo "FastAPI service was not running."
  fi
}

stop_bot() {
  if pkill -f "app.telegram_bot" 2>/dev/null; then
    echo "Stopped Telegram Bot service."
  else
    echo "Telegram Bot service was not running."
  fi
}

stop_llama() {
  if pkill -f "llama-server.*8001" 2>/dev/null; then
    echo "Stopped local llama-server."
  else
    echo "Local llama-server was not running."
  fi
}

stop_frontend() {
  if pkill -f "vite.*5173" 2>/dev/null; then
    echo "Stopped frontend visualizer service."
  else
    echo "Frontend visualizer service was not running."
  fi
}

case "$TARGET" in
  api)
    stop_api
    ;;
  bot)
    stop_bot
    ;;
  llama)
    stop_llama
    ;;
  frontend)
    stop_frontend
    ;;
  all)
    stop_api
    stop_bot
    stop_llama
    stop_frontend
    ;;
  *)
    echo "Usage: $0 [all|api|bot|llama|frontend]" >&2
    exit 1
    ;;
esac