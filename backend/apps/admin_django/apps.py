from django.apps import AppConfig


class AdminDjangoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.admin_django'
    verbose_name = 'Django Admin Extensions'
    
    def ready(self):
        """Import signal handlers when app is ready"""
        try:
            from . import admin_customizations
        except ImportError:
            pass