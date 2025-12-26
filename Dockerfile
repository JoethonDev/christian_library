# Multi-stage Docker build for Christian Library Production
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    DEBIAN_FRONTEND=noninteractive

#==============================================================================
# System Dependencies Stage
#==============================================================================
FROM base AS system-deps

# Install system dependencies including media processing tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Database clients
    postgresql-client \
    # Network tools
    curl \
    # Media processing (essential only)
    ffmpeg \
    poppler-utils \
    ghostscript \
    imagemagick \
    # OCR dependencies
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng \
    # Image processing
    libjpeg62-turbo-dev \
    libpng-dev \
    # Utilities
    supervisor \
    nginx \
    gettext \
    # Build tools (minimal)
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Configure ImageMagick security policy for PDF processing (if exists)
RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
        sed -i '/disable ghostscript format types/,+6d' /etc/ImageMagick-6/policy.xml && \
        sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml; \
    elif [ -f /etc/ImageMagick-7/policy.xml ]; then \
        sed -i '/disable ghostscript format types/,+6d' /etc/ImageMagick-7/policy.xml && \
        sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-7/policy.xml; \
    fi

#==============================================================================
# Python Dependencies Stage  
#==============================================================================
FROM system-deps AS python-deps

# Create app user and directories
RUN groupadd -r app && useradd -r -g app -d /app -s /bin/bash app && \
    mkdir -p /app/staticfiles /app/media /app/logs /app/backups /var/log/nginx && \
    chown -R app:app /app && \
    chown -R app:app /var/log/nginx

WORKDIR /app

# Copy and install Python requirements
COPY backend/requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/production.txt && \
    pip install --no-cache-dir \
        gunicorn[gevent]==21.2.0 \
        whitenoise==6.6.0 \
        django-redis==5.4.0 \
        celery[redis]==5.3.4

#==============================================================================
# Application Stage
#==============================================================================
FROM python-deps AS application

# Copy application code
COPY backend/ /app/
RUN chown -R app:app /app

# Copy configuration files
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create nginx pid directory
RUN mkdir -p /var/run/nginx && chown -R app:app /var/run/nginx

# Create entrypoint script
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && chown app:app /app/entrypoint.sh

# Create health check script
COPY docker/healthcheck.sh /app/healthcheck.sh
RUN chmod +x /app/healthcheck.sh && chown app:app /app/healthcheck.sh

# Switch to app user
USER app

# Expose ports
EXPOSE 8000 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /app/healthcheck.sh

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]