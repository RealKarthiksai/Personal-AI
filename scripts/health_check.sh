#!/usr/bin/env bash
# Comprehensive health check for all Karna components:
# 1. Local AI Model (llama-server on port 8001)
# 2. FastAPI Health Service (uvicorn on port 8000)
# 3. Telegram Bot (long polling process)
set -euo pipefail

echo "=== Karna System Health Check ==="
echo

# 1. Check Local LLM Server
echo "1. Checking Local LLM Server (http://127.0.0.1:8001)..."
LLM_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/v1/models || true)
if [ "$LLM_STATUS" = "200" ]; then
  MODEL_NAME=$(curl -s http://127.0.0.1:8001/v1/models | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo "   [OK] llama-server is healthy (HTTP 200). Discovered model: ${MODEL_NAME:-unknown}"
else
  echo "   [FAIL] llama-server is NOT responding on port 8001 (HTTP $LLM_STATUS)." >&2
fi

# 2. Check FastAPI Service
echo "2. Checking FastAPI Service (http://127.0.0.1:8000)..."
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health || true)
if [ "$API_STATUS" = "200" ]; then
  echo "   [OK] FastAPI app is healthy (HTTP 200):"
  curl -s http://127.0.0.1:8000/health
  echo
else
  echo "   [FAIL] FastAPI app health check failed (HTTP $API_STATUS)." >&2
fi

# 3. Check Telegram Bot Process
echo "3. Checking Telegram Bot..."
if pgrep -f "app.telegram_bot" > /dev/null; then
  BOT_PID=$(pgrep -f "app.telegram_bot" | head -1)
  echo "   [OK] Telegram bot is running (PID: $BOT_PID)."
else
  echo "   [FAIL] Telegram bot is NOT running." >&2
fi

echo
echo "=== Summary ==="
if [ "$LLM_STATUS" = "200" ] && [ "$API_STATUS" = "200" ] && pgrep -f "app.telegram_bot" > /dev/null; then
  echo "ALL SERVICES ARE OPERATIONAL AND HEALTHY!"
  exit 0
else
  echo "SOME SERVICES ARE NOT HEALTHY." >&2
  exit 1
fi