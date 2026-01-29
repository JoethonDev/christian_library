from django.apps import AppConfig


class MediaManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.media_manager'
    verbose_name = 'إدارة الوسائط'
    
    def ready(self):
        import apps.media_manager.signals
        # Phase 4: Import cache invalidation signals
        import apps.media_manager.signals.cache_invalidation