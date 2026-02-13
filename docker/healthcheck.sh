#!/bin/bash
set -e

# Lightweight healthcheck
# 0 = Healthy, 1 = Unhealthy

check_url() {
    if command -v curl >/dev/null 2>&1; then
        curl -f -s -o /dev/null "$1"
    else
        wget -q --spider "$1"
    fi
}

case "$1" in
    celery)
        # Check for celery process
        pgrep -f "celery" > /dev/null
        ;;
    *)
        # Default web check
        check_url "http://localhost:8000/health/" || exit 1
        ;;
esac