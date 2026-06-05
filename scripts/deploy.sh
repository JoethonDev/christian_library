#!/bin/bash
set -euo pipefail

IMAGE_TAG=${1:?Usage: deploy.sh <image-tag>}
ACTIVE_SLOT_FILE=/etc/deploy/active_slot
ACTIVE=$(cat "$ACTIVE_SLOT_FILE" 2>/dev/null || echo "blue")
NEW=$([ "$ACTIVE" = "blue" ] && echo "green" || echo "blue")

OLD_QUEUES=()

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Active:  $ACTIVE  (serving traffic)"
echo "  New:     $NEW     (initializing)"
echo "  Image:   christian-library-app:$IMAGE_TAG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_SHARED="-f ${PROJECT_DIR}/docker-compose.shared.yml"
COMPOSE_NEW="-f ${PROJECT_DIR}/docker-compose.${NEW}.yml"
COMPOSE_OLD="-f ${PROJECT_DIR}/docker-compose.${ACTIVE}.yml"

# ── Step 1: Ensure shared services are up ────────────────────────────
# Handles first-time deploy where no shared stack exists yet.
echo "[1/9] Ensuring shared services are running..."
if ! docker compose $COMPOSE_SHARED ps --status running 2>/dev/null | grep -q "redis"; then
  echo "      Shared stack not detected. Starting shared services..."
  docker compose $COMPOSE_SHARED up -d --wait db redis
fi
echo "      Shared services OK"

# ── Step 2: Build image ─────────────────────────────────────────────
echo "[2/9] Building image christian-library-app:${IMAGE_TAG}..."
docker build -t christian-library-app:"${IMAGE_TAG}" -f "${PROJECT_DIR}/Dockerfile" "${PROJECT_DIR}"
docker tag christian-library-app:"${IMAGE_TAG}" christian-library-app:latest

# ── Step 3: Run migrations ──────────────────────────────────────────
echo "[3/9] Running migrations..."
# Override image tag for the migration service
export IMAGE_TAG
docker compose $COMPOSE_SHARED run --rm migration \
  python manage.py migrate --no-input
echo "      Migrations OK"

# ── Step 4: Start new slot ──────────────────────────────────────────
echo "[4/9] Starting new slot: $NEW..."
docker compose $COMPOSE_SHARED $COMPOSE_NEW up -d --force-recreate

# ── Step 5: Wait for health check ───────────────────────────────────
echo "[5/9] Waiting for $NEW to become healthy..."
RETRIES=0
MAX_RETRIES=30
until docker inspect "app_${NEW}" \
    --format='{{.State.Health.Status}}' 2>/dev/null | grep -q "^healthy$"; do
  RETRIES=$((RETRIES + 1))
  if [ $RETRIES -ge $MAX_RETRIES ]; then
    echo "      TIMEOUT: $NEW never became healthy. Tearing down."
    docker compose $COMPOSE_SHARED $COMPOSE_NEW down
    echo "      Old slot ($ACTIVE) is still serving. Deploy aborted."
    exit 1
  fi
  echo "      ... attempt $RETRIES/$MAX_RETRIES"
  sleep 3
done
echo "      $NEW is healthy"

# ── Step 6: Smoke tests ─────────────────────────────────────────────
echo "[6/9] Running smoke tests against $NEW..."
"${PROJECT_DIR}/scripts/smoke_test.sh" "$NEW" || {
  echo "      FAILED: smoke tests did not pass. Tearing down $NEW."
  docker compose $COMPOSE_SHARED $COMPOSE_NEW down
  echo "      Old slot ($ACTIVE) is still serving. Deploy aborted."
  exit 1
}
echo "      Smoke tests passed"

# ── Step 7: Switch Nginx, then stop old slot ────────────────────────
echo "[7/9] Switching traffic from $ACTIVE to $NEW..."

UPSTREAM_FILE="${PROJECT_DIR}/docker/nginx/conf.d/upstream.conf"
echo "upstream active_backend { server app_${NEW}:8000; keepalive 32; }" \
  > "$UPSTREAM_FILE"
docker exec nginx nginx -t
docker exec nginx nginx -s reload

echo "$NEW" > "$ACTIVE_SLOT_FILE"

sleep 3

echo "      Stopping old slot: $ACTIVE..."
docker compose $COMPOSE_SHARED $COMPOSE_OLD down || true

# ── Step 8: Drain removed queues ────────────────────────────────────
echo "[8/9] Draining old queues..."
if [ ${#OLD_QUEUES[@]} -eq 0 ]; then
  echo "      No queues to drain. Skipping."
else
  for QUEUE in "${OLD_QUEUES[@]}"; do
    echo "      Waiting for $QUEUE to drain..."
    RETRIES=0
    MAX_RETRIES=20
    until [ "$(docker exec redis redis-cli LLEN "$QUEUE")" = "0" ]; do
      RETRIES=$((RETRIES + 1))
      if [ $RETRIES -ge $MAX_RETRIES ]; then
        REMAINING=$(docker exec redis redis-cli LLEN "$QUEUE")
        echo ""
        echo "      WARNING: $QUEUE did not drain in time ($REMAINING tasks remaining)."
        echo "      Workers are about to restart and will DROP this listener."
        echo "      Those tasks will be lost."
        read -rp "      Continue anyway? [y/N] " confirm
        [[ "$confirm" = "y" ]] || { echo "Deploy aborted."; exit 1; }
        break
      fi
      REMAINING=$(docker exec redis redis-cli LLEN "$QUEUE")
      echo "      ... $QUEUE has $REMAINING tasks remaining (attempt $RETRIES/$MAX_RETRIES)"
      sleep 3
    done
    echo "      $QUEUE drained OK"
  done
fi

# ── Step 9: Restart workers with new image ──────────────────────────
echo "[9/9] Restarting workers with new image..."
WORKERS=(celery_worker_primary celery_worker_secondary celery_worker_uploads celery_worker_gemini)
for WORKER in "${WORKERS[@]}"; do
  echo "      Restarting $WORKER..."
  docker compose $COMPOSE_SHARED restart "$WORKER"
  sleep 5
done
echo "      Restarting beat..."
docker compose $COMPOSE_SHARED restart celery_beat

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deploy complete. Active slot: $NEW"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
