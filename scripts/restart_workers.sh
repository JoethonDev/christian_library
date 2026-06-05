#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_SHARED="-f ${PROJECT_DIR}/docker-compose.shared.yml"

WORKERS=(celery_worker_primary celery_worker_secondary celery_worker_uploads celery_worker_gemini)

for WORKER in "${WORKERS[@]}"; do
  echo "Restarting $WORKER..."
  docker compose $COMPOSE_SHARED restart "$WORKER"
  sleep 5
done

echo "Restarting beat..."
docker compose $COMPOSE_SHARED restart celery_beat
echo "Workers done."
