import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-development-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'testserver']

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'corsheaders',
]

LOCAL_APPS = [
    'apps.media_manager',
    'apps.users',
    'apps.frontend_api',
    'apps.admin_django',  # Django admin enhancements
    'core.apps.CoreConfig',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.performance.PerformanceMonitoringMiddleware',
    'core.middleware.security.SecurityHeadersMiddleware',
    'core.middleware.db_query_metrics.UnifiedDBQueryMetricsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'apps.media_manager.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'christian_library'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c default_transaction_isolation=read_committed'
        },
        'CONN_MAX_AGE': 600,  # 10 minutes connection pooling
        'ATOMIC_REQUESTS': True,  # Wrap each request in a transaction
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ('ar', 'العربية'),
    ('en', 'English'),
]

# Gemini AI Configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3-flash-preview')

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- Cloudflare R2 / S3-Compatible Storage Settings ---
# These settings enable optional integration with Cloudflare R2 or any S3-compatible storage.
# If not set, the system will use local storage as before (backward compatible).
R2_ENABLED = os.environ.get('R2_ENABLED', 'False').lower() == 'true'
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', '')
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '')
R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL', '')  # e.g., 'https://<accountid>.r2.cloudflarestorage.com'
R2_REGION_NAME = os.environ.get('R2_REGION_NAME', 'auto')
R2_PUBLIC_MEDIA_URL = os.environ.get('R2_PUBLIC_MEDIA_URL', '')  # e.g., 'https://pub-<public-id>.r2.dev'

# Optional: Use a custom storage backend if R2 is enabled (to be implemented)
if R2_ENABLED:
    DEFAULT_FILE_STORAGE = 'core.storage_backends.R2MediaStorage'
    # MEDIA_URL should point to the public R2 bucket URL if using public access
    if os.environ.get('R2_PUBLIC_MEDIA_URL'):
        MEDIA_URL = os.environ['R2_PUBLIC_MEDIA_URL']

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Redis configuration
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'retry_on_timeout': True,
                'socket_keepalive': True,
                'socket_keepalive_options': {},
            },
            'IGNORE_EXCEPTIONS': True,  # Fail silently if Redis is down
        },
        'KEY_PREFIX': 'christian_library',
        'TIMEOUT': 300,  # 5 minutes default timeout
    },
    # Separate cache for query results (longer TTL)
    'query_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f"{REDIS_URL}/1",  # Different Redis DB
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'retry_on_timeout': True,
                'socket_keepalive': True,
            },
            'IGNORE_EXCEPTIONS': True,
        },
        'KEY_PREFIX': 'query_cache',
        'TIMEOUT': 900,  # 15 minutes for query results
    },
    # Cache for statistics and aggregations (medium TTL)
    'stats_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f"{REDIS_URL}/2",  # Different Redis DB  
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'retry_on_timeout': True,
                'socket_keepalive': True,
            },
            'IGNORE_EXCEPTIONS': True,
        },
        'KEY_PREFIX': 'stats_cache',
        'TIMEOUT': 1800,  # 30 minutes for statistics
    },
    # Cache for search results (shorter TTL due to frequent updates)
    'search_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f"{REDIS_URL}/3",  # Different Redis DB
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'retry_on_timeout': True,
                'socket_keepalive': True,
            },
            'IGNORE_EXCEPTIONS': True,
        },
        'KEY_PREFIX': 'search_cache', 
        'TIMEOUT': 600,  # 10 minutes for search results
    },
}

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'
SESSION_COOKIE_AGE = 86400  # 24 hours

# Celery Configuration
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ACKS_LATE = True

# Celery 6.0+ compatibility: retry broker connection on startup
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Periodic tasks
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'cleanup-failed-uploads': {
        'task': 'core.tasks.media_processing.cleanup_failed_uploads',
        'schedule': 3600.0,  # Run every hour
    },
    'aggregate-daily-content-views': {
        'task': 'apps.media_manager.tasks.aggregate_daily_content_views',
        'schedule': crontab(hour=0, minute=0),  # Run daily at midnight
    },
}

# File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'EXCEPTION_HANDLER': 'core.utils.exceptions.custom_exception_handler',
}

# Custom user model
AUTH_USER_MODEL = 'users.User'

# Admin Site Configuration
ADMIN_SITE_HEADER = 'المكتبة المسيحية - لوحة التحكم'
ADMIN_SITE_TITLE = 'إدارة المكتبة'
ADMIN_INDEX_TITLE = 'مرحباً بك في لوحة تحكم المكتبة المسيحية'

# Security Settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# CORS Settings
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:80",
    "http://127.0.0.1:80",
]

# Logging Configuration
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
        'json': {
            'format': '{"level": "{levelname}", "time": "{asctime}", "module": "{module}", "message": "{message}"}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'json',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
        },
        'core': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
        },
        'apps': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
        },
    },
}

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:80",
    "http://127.0.0.1:80",
]
# FIX: Added CORS_ALLOWED_ORIGIN_REGEXES for development flexibility
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^http://localhost:\d+$',
    r'^http://127\.0\.0\.1:\d+$',
]

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyB286GvUw1X1yl8cwjMbGIZkFv40BMttTk')