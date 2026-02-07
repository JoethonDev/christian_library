from .models import SiteConfiguration

def site_settings(request):
    """
    Makes site configuration available to all templates.
    """
    try:
        # We cache this to avoid repeated DB hits on every page
        from django.core.cache import cache
        config = cache.get('site_configuration')
        if config is None:
            config = SiteConfiguration.objects.first()
            if config:
                cache.set('site_configuration', config, 3600) # Cache for 1 hour
    except:
        config = None
        
    return {
        'site_config': config
    }
