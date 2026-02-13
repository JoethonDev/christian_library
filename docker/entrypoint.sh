#!/bin/bash
set -e

# Production Entrypoint
# Handles database waiting, migrations, and service start

wait_for_service() {
    local host=$1
    local port=$2
    local service=$3
    echo "⏳ Waiting for $service ($host:$port)..."
    while ! timeout 1 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; do
        sleep 1
    done
    echo "✅ $service is ready."
}

# Main Switch
case "$1" in
    web)
        wait_for_service "${DB_HOST:-db}" "${DB_PORT:-5432}" "PostgreSQL"
        wait_for_service "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "Redis"
        
        echo "📦 Collecting static files..."
        python manage.py collectstatic --noinput --clear

        echo "🗃️  Checking migrations..."
        # In production, automated migrations can be risky. 
        # Uncomment next line if you want auto-migrations on startup.
        python manage.py migrate --noinput
        
        echo "🚀 Starting Gunicorn (Gevent)..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers ${GUNICORN_WORKERS:-3} \
            --worker-class gevent \
            --worker-connections 1000 \
            --access-logfile - \
            --error-logfile -
        ;;

    worker)
        wait_for_service "${DB_HOST:-db}" "${DB_PORT:-5432}" "PostgreSQL"
        wait_for_service "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "Redis"
        
        echo "👷 Starting Celery Worker..."
        exec celery -A config worker -l info --concurrency=${CELERY_CONCURRENCY:-2}
        ;;

    beat)
        wait_for_service "${DB_HOST:-db}" "${DB_PORT:-5432}" "PostgreSQL"
        wait_for_service "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "Redis"
        
        echo "⏰ Starting Celery Beat..."
        # Use /tmp for pid and schedule files to avoid permission/locking issues in /app
        rm -f /tmp/celerybeat.pid
        # Verify python path and settings
        echo "🔍 Environment: DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"
        exec celery -A config beat -l info --pidfile=/tmp/celerybeat.pid --schedule=/tmp/celerybeat-schedule
        ;;
        
    supervisord)
        echo "👮 Starting Supervisord..."
        exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
        ;;

    *)
        exec "$@"
        ;;
esac