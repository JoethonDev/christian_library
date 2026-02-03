from .base import *
import os

# Production settings
# DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
DEBUG = True
print(f"Production settings loaded. DEBUG={DEBUG}")
# Keep APP_DIRS enabled for admin templates
# TEMPLATES[0]['APP_DIRS'] = False  # Disable APP_DIRS for performance in production
# Security
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required in production")

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS if host.strip()]

# Security settings for production
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False').lower() == 'true'
SECURE_PROXY_SSL_HEADER = (
    os.getenv('SECURE_PROXY_SSL_HEADER_NAME', 'HTTP_X_FORWARDED_PROTO'),
    os.getenv('SECURE_PROXY_SSL_HEADER_VALUE', 'https')
)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True').lower() == 'true'
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Session and CSRF security
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 1209600  # 2 weeks
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'False').lower() == 'true'
CSRF_COOKIE_HTTPONLY = True

# Database with environment variables
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'christian_library_db'),
        'USER': os.getenv('DB_USER', 'christian_library_user'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'db'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '600')),
        'OPTIONS': {
            'connect_timeout': 60,
        },
    }
}

# Redis cache for production
REDIS_URL = f"redis://:{os.getenv('REDIS_PASSWORD', '')}@{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}"

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f"{REDIS_URL}/{os.getenv('REDIS_DB', '1')}",
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            },
        },
    }
}

# Session engine
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Celery configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f"{REDIS_URL}/0")
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv('CELERY_PREFETCH_MULTIPLIER', '1'))
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(os.getenv('CELERY_MAX_TASKS_PER_CHILD', '1000'))

# Celery 6.0+ compatibility: retry broker connection on startup
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Static and media files
STATIC_URL = '/static/'
STATIC_ROOT = os.getenv('STATIC_ROOT', '/app/staticfiles')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/app/media')

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('FILE_UPLOAD_MAX_MEMORY_SIZE', str(1024 * 1024 * 1024 * 2)))  # 2GB
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('DATA_UPLOAD_MAX_MEMORY_SIZE', str(1024 * 1024 * 1024 * 2)))  # 2GB
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv('DATA_UPLOAD_MAX_NUMBER_FIELDS', '1000'))

# Email configuration
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
if EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
    EMAIL_HOST = os.getenv('EMAIL_HOST')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Christian Library <noreply@localhost>')

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/app/logs/django.log',
            'maxBytes': 50 * 1024 * 1024,  # 50MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'celery': {
            'handlers': ['file', 'console'],
            'level': os.getenv('CELERY_LOG_LEVEL', 'INFO').upper(),
            'propagate': False,
        },
        'apps': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Internationalization
LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'en')
TIME_ZONE = os.getenv('TIME_ZONE', 'UTC')
USE_TZ = True

# Performance optimizations can be added later if needed
# For now, use the base template configuration to avoid conflicts

# Media processing settings
MEDIA_PROCESSING = {
    'ENABLE_DEPENDENCY_CHECK': True,
    'DEPENDENCY_CHECK_TIMEOUT': 30,
    'VIDEO_FORMATS': ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm'],
    'AUDIO_FORMATS': ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'],
    'DOCUMENT_FORMATS': ['pdf', 'doc', 'docx'],
    'COMPRESSION_QUALITY': 85,
    'THUMBNAIL_SIZE': (300, 300),
    'MAX_FILE_SIZE': 5 * 1024 * 1024 * 1024,  # 5GB
}

# Nginx media serving
NGINX_MEDIA_SERVING = {
    'ENABLE_X_ACCEL_REDIRECT': True,
    'INTERNAL_MEDIA_URL': '/internal/media/',
    'PUBLIC_MEDIA_PATH': '/media/public/',
    'SECURE_DOWNLOAD_URL': '/core/media/secure/',
    'SECURE_STREAM_URL': '/core/media/stream/',
}