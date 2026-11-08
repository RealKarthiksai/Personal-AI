#!/usr/bin/env bash
# Start the Karna Frontend visualizer (Vite React).
# Usage: ./scripts/start_frontend.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "ERROR: Frontend directory not found at $FRONTEND_DIR" >&2
  exit 1
fi

cd "$FRONTEND_DIR"
echo "Starting Karna Frontend on http://127.0.0.1:5173"
exec npm run dev -- --host 127.0.0.1 --port 5173
