#!/usr/bin/env bash
# Start the local llama.cpp server with Qwen 3.5 2B.
# Usage: ./scripts/start_llama.sh
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-/home/vhanghar/.local/share/lacc/models/qwen3.5-2b/models--gguf--Qwen3.5-2B-GGUF/snapshots/47f5192dcee31b32db0ba0acc04cccef89cb4b2c/qwen3.5-2b-Q4_K_M.gguf}"
PORT=8001
HOST=127.0.0.1

if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: Model file not found at $MODEL_PATH" >&2
  exit 1
fi

if ! command -v llama-server &>/dev/null; then
  echo "ERROR: llama-server binary not found on PATH" >&2
  exit 1
fi

echo "Starting llama-server on http://${HOST}:${PORT} with model $(basename "$MODEL_PATH")..."
exec /usr/bin/llama-server \
  -m "$MODEL_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  -c 4096 \
  --alias qwen3.5-2b \
  -t 8 \
  --parallel 1 \
  --reasoning-budget 0
