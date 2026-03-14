"""
Development settings for Christian Library project.

For personal local overrides (e.g., different database, debug toolbar settings),
create a local.py file in this directory:
    from .development import *
    # Your overrides here
Then set: DJANGO_SETTINGS_MODULE=config.settings.local
"""
from .base import *

# Development specific settings
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']

# Use http for local development
SITE_PROTOCOL = 'http'


INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
]

# Development database - using SQLite for easier initial setup
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Simple console logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'