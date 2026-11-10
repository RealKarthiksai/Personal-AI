#!/usr/bin/env bash
# Dual-model server runner for Multi-Stage Pipeline (Fast on :8081, Smart on :8082)
set -euo pipefail

M="/home/vhanghar/.local/share/lacc/models"
FAST_4B="$M/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf"
FAST_2B="$M/qwen3.5-2b/models--gguf--Qwen3.5-2B-GGUF/snapshots/47f5192dcee31b32db0ba0acc04cccef89cb4b2c/qwen3.5-2b-Q4_K_M.gguf"
SMART_9B="$M/qwen3.5-9b/Qwen3.5-9B-Q4_K_M.gguf"

if ! command -v llama-server &>/dev/null; then
  echo "ERROR: llama-server binary not found on PATH" >&2
  exit 1
fi

# Determine Fast Model: prefer 4B if present, else Plan B (2B)
if [ -f "$FAST_4B" ]; then
  FAST="$FAST_4B"
  FAST_ALIAS="qwen3.5-4b"
elif [ -f "$FAST_2B" ]; then
  FAST="$FAST_2B"
  FAST_ALIAS="qwen3.5-2b"
  echo "Plan B: Using 2B model for Fast Planner role on :8081"
else
  echo "ERROR: Neither 4B nor 2B fast model found at $M" >&2
  exit 1
fi

# Smart Model: 9B is required
if [ ! -f "$SMART_9B" ]; then
  echo "ERROR: Smart model file not found at $SMART_9B" >&2
  echo "Please wait for the download to complete or check the path." >&2
  exit 1
fi
SMART="$SMART_9B"
SMART_ALIAS="qwen3.5-9b"

echo "=== Starting Multi-Stage LLM Servers ==="
echo "Fast Server  (:8081): $(basename "$FAST")"
echo "Smart Server (:8082): $(basename "$SMART")"

/usr/bin/llama-server \
  -m "$FAST" \
  --host 127.0.0.1 \
  --port 8081 \
  -c 4096 \
  -t 4 \
  --parallel 1 \
  --alias "$FAST_ALIAS" &
FAST_PID=$!

/usr/bin/llama-server \
  -m "$SMART" \
  --host 127.0.0.1 \
  --port 8082 \
  -c 8192 \
  -t 8 \
  --parallel 1 \
  --alias "$SMART_ALIAS" &
SMART_PID=$!

cleanup() {
  echo "Stopping LLM servers..."
  kill "$FAST_PID" "$SMART_PID" 2>/dev/null || true
  wait "$FAST_PID" "$SMART_PID" 2>/dev/null || true
}
trap cleanup SIGINT SIGTERM EXIT

echo "Both servers running. Press Ctrl+C to terminate."
wait
