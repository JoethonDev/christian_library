#!/bin/bash
set -e

echo "🚀 Starting Christian Library Application..."

# Function to wait for service
wait_for_service() {
    local service=$1
    local host=$2
    local port=$3
    local timeout=${4:-60}
    
    echo "⏳ Waiting for $service at $host:$port..."
    
    for i in $(seq 1 $timeout); do
        if timeout 1 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
            echo "✅ $service is ready!"
            return 0
        fi
        sleep 1
    done
    
    echo "❌ $service is not available after ${timeout}s"
    return 1
}

# Function to check system dependencies
check_dependencies() {
    echo "🔍 Checking system dependencies..."
    
    local missing_deps=()
    
    # Check FFmpeg
    if ! command -v ffmpeg >/dev/null 2>&1; then
        missing_deps+=("ffmpeg")
    fi
    
    # Check Ghostscript
    if ! command -v gs >/dev/null 2>&1; then
        missing_deps+=("ghostscript")
    fi
    
    # Check pdfinfo (poppler-utils)
    if ! command -v pdfinfo >/dev/null 2>&1; then
        missing_deps+=("poppler-utils")
    fi
    
    # Check ImageMagick
    if ! command -v convert >/dev/null 2>&1; then
        missing_deps+=("imagemagick")
    fi
    
    if [ ${#missing_deps[@]} -eq 0 ]; then
        echo "✅ All system dependencies are available"
        return 0
    else
        echo "❌ Missing dependencies: ${missing_deps[*]}"
        return 1
    fi
}

# Function to setup Django
setup_django() {
    echo "🔧 Setting up Django application..."
    
    # Run migrations
    echo "🗃️  Generate database migrations..."
    python manage.py makemigrations

    # Run migrations
    echo "🗃️  Running database migrations..."
    python manage.py migrate
    
    # Collect static files
    echo "📦 Collecting static files..."
    python manage.py collectstatic --noinput --clear
    
    # Create superuser if it doesn't exist
    echo "👤 Setting up admin user..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('✅ Admin user created: admin/admin123')
else:
    print('✅ Admin user already exists')
"
    
    # Create media directories
    echo "📁 Setting up media directories..."
    mkdir -p /app/media/{original,compressed,optimized,hls,public}
    chown -R app:app /app/media/
    chmod -R 755 /app/media/
    
    echo "✅ Django setup completed!"
}

# Function to test media processing
test_media_processing() {
    echo "🧪 Testing media processing capabilities..."
    
    python manage.py shell -c "
import sys
from core.utils.media_processing import check_dependencies

try:
    missing = check_dependencies()
    if missing:
        print(f'❌ Missing dependencies: {missing}')
        sys.exit(1)
    else:
        print('✅ All media processing dependencies available')
except Exception as e:
    print(f'❌ Error checking dependencies: {e}')
    sys.exit(1)
"
}

# Main execution
case "$1" in
    web)
        echo "🌐 Starting web server..."
        
        # Wait for database
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        
        # Wait for Redis
        wait_for_service "Redis" "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"
        
        # Check dependencies
        check_dependencies || {
            echo "⚠️  Some dependencies missing, but continuing..."
        }
        
        # Setup Django
        setup_django
        
        # Test media processing
        test_media_processing || {
            echo "⚠️  Media processing test failed, but continuing..."
        }
        
        echo "🚀 Starting Gunicorn server..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers ${GUNICORN_WORKERS:-3} \
            --worker-class ${GUNICORN_WORKER_CLASS:-gevent} \
            --worker-connections ${GUNICORN_WORKER_CONNECTIONS:-1000} \
            --max-requests ${GUNICORN_MAX_REQUESTS:-1000} \
            --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-100} \
            --timeout ${GUNICORN_TIMEOUT:-300} \
            --keep-alive ${GUNICORN_KEEP_ALIVE:-5} \
            --access-logfile - \
            --error-logfile - \
            --log-level ${LOG_LEVEL:-info}
        ;;
        
    worker)
        echo "👷 Starting Celery worker..."
        
        # Wait for database
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        
        # Wait for Redis
        wait_for_service "Redis" "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"
        
        # Check dependencies
        check_dependencies || {
            echo "❌ Cannot start worker without media processing dependencies!"
            exit 1
        }
        
        echo "🚀 Starting Celery worker..."
        exec celery -A config worker \
            --loglevel=${CELERY_LOG_LEVEL:-info} \
            --concurrency=${CELERY_CONCURRENCY:-2} \
            --prefetch-multiplier=${CELERY_PREFETCH_MULTIPLIER:-1} \
            --max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD:-1000}
        ;;
        
    beat)
        echo "⏰ Starting Celery beat..."
        
        # Wait for database
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        
        # Wait for Redis
        wait_for_service "Redis" "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"
        
        echo "🚀 Starting Celery beat..."
        exec celery -A config beat \
            --loglevel=${CELERY_LOG_LEVEL:-info} \
            --pidfile=/tmp/celerybeat.pid \
            --schedule=/tmp/celerybeat-schedule
        ;;
        
    nginx)
        echo "🌐 Starting Nginx..."
        
        # Wait for backend
        wait_for_service "Django Backend" "backend" "8000"
        
        # Test nginx configuration
        nginx -t || {
            echo "❌ Nginx configuration test failed!"
            exit 1
        }
        
        echo "🚀 Starting Nginx..."
        exec nginx -g "daemon off;"
        ;;
        
    migrate)
        echo "🗃️  Running migrations only..."
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        exec python manage.py migrate --noinput
        ;;
        
    collectstatic)
        echo "📦 Collecting static files only..."
        exec python manage.py collectstatic --noinput --clear
        ;;
        
    shell)
        echo "🐚 Starting Django shell..."
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        exec python manage.py shell
        ;;
        
    test)
        echo "🧪 Running tests..."
        wait_for_service "PostgreSQL" "${DB_HOST:-db}" "${DB_PORT:-5432}"
        exec python manage.py test
        ;;
        
    *)
        echo "Usage: $0 {web|worker|beat|nginx|migrate|collectstatic|shell|test}"
        echo ""
        echo "Commands:"
        echo "  web           - Start Django web server with Gunicorn"
        echo "  worker        - Start Celery worker for background tasks"
        echo "  beat          - Start Celery beat scheduler"
        echo "  nginx         - Start Nginx reverse proxy"
        echo "  migrate       - Run database migrations"
        echo "  collectstatic - Collect static files"
        echo "  shell         - Start Django shell"
        echo "  test          - Run tests"
        exit 1
        ;;
esac