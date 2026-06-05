#!/bin/bash
set -euo pipefail

SLOT=$1
CONTAINER="app_${SLOT}"

echo "Running smoke tests against $CONTAINER..."

# 1. Health endpoint
docker exec "$CONTAINER" curl -sf http://localhost:8000/health/ \
  || { echo "FAIL: health check"; exit 1; }

# 2. App root returns 200 or 301 (not 500)
STATUS=$(docker exec "$CONTAINER" \
  curl -o /dev/null -sw "%{http_code}" http://localhost:8000/)
[[ "$STATUS" =~ ^(200|301|302)$ ]] \
  || { echo "FAIL: root returned $STATUS"; exit 1; }

echo "Smoke tests PASSED for $SLOT"
