#!/usr/bin/env bash
# Start or manage local SearXNG container
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.searxng.yml"

action="${1:-start}"

case "$action" in
    start)
        echo "Starting SearXNG container..."
        docker compose -f "${COMPOSE_FILE}" up -d
        echo "Waiting for SearXNG on http://127.0.0.1:8080/healthz..."
        for i in {1..15}; do
            if curl -fs "http://127.0.0.1:8080/healthz" > /dev/null 2>&1 || curl -fs "http://127.0.0.1:8080/" > /dev/null 2>&1; then
                echo "SearXNG is ready on http://127.0.0.1:8080"
                exit 0
            fi
            sleep 1
        done
        echo "SearXNG container started (healthcheck pending)."
        ;;
    stop)
        echo "Stopping SearXNG container..."
        docker compose -f "${COMPOSE_FILE}" down
        ;;
    restart)
        echo "Restarting SearXNG..."
        docker compose -f "${COMPOSE_FILE}" restart
        ;;
    status)
        docker compose -f "${COMPOSE_FILE}" ps
        ;;
    *)
        echo "Usage: $0 [start|stop|restart|status]"
        exit 1
        ;;
esac
