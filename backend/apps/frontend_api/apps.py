from django.apps import AppConfig


class FrontendApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.frontend_api'
    verbose_name = 'واجهة برمجة تطبيقات الواجهة'
    
    def ready(self):
        """Initialize site settings and import signals"""
        # Ensure Site object matches settings/env
        try:
            from django.conf import settings
            from django.contrib.sites.models import Site
            
            # Use IDs and domains from settings/env
            site_id = getattr(settings, 'SITE_ID', 1)
            site_domain = getattr(settings, 'SITE_DOMAIN', 'localhost')
            site_name = getattr(settings, 'SITE_NAME', 'Christian Library')
            
            # One-time sync: update existing or create
            Site.objects.filter(id=site_id).update(domain=site_domain, name=site_name)
            # If it doesn't exist, create it (careful with IDs as they are often auto-inc)
            if not Site.objects.filter(id=site_id).exists():
                Site.objects.create(id=site_id, domain=site_domain, name=site_name)
        except Exception:
            # Avoid crashing if database table doesn't exist yet (during migrations)
            pass
            
        import apps.frontend_api.signals_sitemap  # noqa