from django.apps import AppConfig


class FrontendApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.frontend_api'
    verbose_name = 'واجهة برمجة تطبيقات الواجهة'
    
    def ready(self):
        """Import signal handlers when the app is ready"""
        import apps.frontend_api.signals_sitemap  # noqa