# Production Dockerfile for Christian Library
# Base: Python 3.11 Slim (Debian Bookworm)
FROM python:3.11-slim-bookworm AS base

# Python & System Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    # Helper to ensure scripts are found
    PATH="/app:${PATH}"

#==============================================================================
# Builder Stage (Compilers & Heavy Dev Tools)
#==============================================================================
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install python dependencies into a temporary location
COPY backend/requirements/ /build/requirements/
# Combine requirements or install production.txt directly
RUN pip install --no-cache-dir --prefix=/install -r requirements/production.txt && \
    pip install --no-cache-dir --prefix=/install \
        gunicorn[gevent]==21.2.0 \
        whitenoise==6.6.0 \
        django-redis==5.4.0 \
        celery[redis]==5.3.6

#==============================================================================
# Runtime Stage (Final Image)
#==============================================================================
FROM base AS runtime

# Install Runtime Dependencies
# ffmpeg: Media processing
# poppler-utils/ghostscript: PDF processing
# tesseract-ocr: OCR tasks
# nginx: Required if using supervisord to run both (optional, but requested)
# supervisor: Process control
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    poppler-utils \
    ghostscript \
    imagemagick \
    tesseract-ocr \
    tesseract-ocr-ara \
    supervisor \
    curl \
    gettext \
    && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick Policy for PDF
RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
        sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml; \
    fi

# Create secure user
RUN groupadd -r app && useradd -r -g app -d /app -s /bin/false app

WORKDIR /app

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Copy Application Code
COPY --chown=app:app backend/ /app/

# Copy Config Scripts
COPY --chown=app:app docker/entrypoint.sh /app/entrypoint.sh
COPY --chown=app:app docker/healthcheck.sh /app/healthcheck.sh
COPY --chown=app:app docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Fix line endings (CRLF to LF) for Windows compatibility and make executable
RUN sed -i 's/\r$//' /app/entrypoint.sh /app/healthcheck.sh && \
    chmod +x /app/entrypoint.sh /app/healthcheck.sh

# Directory structure for App
RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R app:app /app/staticfiles /app/media /app/logs

# Switch to app user for security
USER app

# Metadata
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]