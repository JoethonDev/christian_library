#!/bin/bash
set -e

# Health check script for the Christian Library application
# This script checks if all services are healthy

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check HTTP endpoint
check_http() {
    local url=$1
    local name=$2
    local expected_status=${3:-200}
    
    echo -n "Checking $name... "
    
    if command -v curl >/dev/null 2>&1; then
        status=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    elif command -v wget >/dev/null 2>&1; then
        if wget -q --spider --timeout=10 "$url" 2>/dev/null; then
            status="200"
        else
            status="000"
        fi
    else
        echo -e "${RED}SKIP${NC} (no curl/wget)"
        return 1
    fi
    
    if [ "$status" = "$expected_status" ]; then
        echo -e "${GREEN}OK${NC} ($status)"
        return 0
    else
        echo -e "${RED}FAIL${NC} ($status)"
        return 1
    fi
}

# Function to check TCP port
check_tcp() {
    local host=$1
    local port=$2
    local name=$3
    
    echo -n "Checking $name ($host:$port)... "
    
    if timeout 5 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
        return 0
    else
        echo -e "${RED}FAIL${NC}"
        return 1
    fi
}

# Function to check system dependencies
check_dependencies() {
    echo "=== System Dependencies ==="
    
    local deps=("ffmpeg" "gs" "pdfinfo" "convert")
    local missing=0
    
    for dep in "${deps[@]}"; do
        echo -n "Checking $dep... "
        if command -v "$dep" >/dev/null 2>&1; then
            echo -e "${GREEN}OK${NC}"
        else
            echo -e "${RED}MISSING${NC}"
            missing=$((missing + 1))
        fi
    done
    
    return $missing
}

# Function to check Django health
check_django() {
    echo "=== Django Application ==="
    
    # Check if we can import Django
    echo -n "Checking Django import... "
    if python -c "import django; print('Django', django.get_version())" >/dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
        return 1
    fi
    
    # Check database connection
    echo -n "Checking database connection... "
    if python manage.py check --database default >/dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
        return 1
    fi
    
    return 0
}

# Function to check Celery
check_celery() {
    echo "=== Celery Status ==="
    
    echo -n "Checking Celery connection... "
    if python -c "
from celery import Celery
from django.conf import settings
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
result = app.control.ping(timeout=10)
print('Celery ping successful' if result else 'No workers responding')
" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${YELLOW}WARN${NC} (no workers or connection issue)"
    fi
}

# Function to check media processing
check_media_processing() {
    echo "=== Media Processing ==="
    
    echo -n "Checking media processing utilities... "
    if python -c "
from core.utils.media_processing import check_dependencies
missing = check_dependencies()
if missing:
    print(f'Missing: {missing}')
    exit(1)
else:
    print('All dependencies available')
" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
        return 1
    fi
}

# Main health check
main() {
    echo "🏥 Christian Library Health Check"
    echo "================================="
    
    local failures=0
    
    # Check system dependencies
    if ! check_dependencies; then
        failures=$((failures + 1))
    fi
    
    echo ""
    
    # Check services based on context
    if [ "$CONTAINER_ROLE" = "web" ] || [ -z "$CONTAINER_ROLE" ]; then
        # Web server checks
        if ! check_django; then
            failures=$((failures + 1))
        fi
        
        echo ""
        
        # Check HTTP endpoints
        echo "=== HTTP Endpoints ==="
        check_http "http://localhost:8000/health/" "Django Health" || failures=$((failures + 1))
        check_http "http://localhost/nginx-health/" "Nginx Health" || true
        
    elif [ "$CONTAINER_ROLE" = "worker" ]; then
        # Worker checks
        if ! check_django; then
            failures=$((failures + 1))
        fi
        
        echo ""
        
        if ! check_media_processing; then
            failures=$((failures + 1))
        fi
        
        echo ""
        
        check_celery
        
    elif [ "$CONTAINER_ROLE" = "nginx" ]; then
        # Nginx checks
        echo "=== Nginx Status ==="
        check_http "http://localhost/nginx-health/" "Nginx Health" || failures=$((failures + 1))
        check_tcp "backend" "8000" "Backend Connection" || failures=$((failures + 1))
    fi
    
    echo ""
    echo "================================="
    
    if [ $failures -eq 0 ]; then
        echo -e "${GREEN}✅ All health checks passed!${NC}"
        exit 0
    else
        echo -e "${RED}❌ $failures health check(s) failed!${NC}"
        exit 1
    fi
}

# Run health check
main "$@"