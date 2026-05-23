"""
Sitemap Auto-Update Signals
Automatically invalidate sitemap cache when content changes
Also notifies Google of sitemap updates via ping

Note: Google Indexing API notifications are handled by apps.media_manager.signals_seo
which only triggers when SEO metadata actually changes (not on every save)
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.media_manager.models import ContentItem
import logging

logger = logging.getLogger(__name__)


@receiver([post_save], sender=ContentItem)
def invalidate_sitemap_cache_and_notify(sender, instance, created, **kwargs):
    """
    Automatically invalidate sitemap cache when content is created or updated
    This ensures sitemaps are always up-to-date without manual intervention
    Also notifies Google of the update
    """
    try:
        # Invalidate home page sitemap cache
        cache.delete('sitemap_home_lastmod')
        
        # Invalidate content type specific cache
        content_type = instance.content_type
        cache.delete(f'sitemap_{content_type}_lastmod')
        
        # Invalidate general sitemap cache if exists
        cache.delete('sitemap_cache')
        
        logger.info(f"Invalidated sitemap cache for content type: {content_type}")
        
        # Only ping sitemap for active content
        if instance.is_active:
            # Import here to avoid circular imports
            from apps.frontend_api.google_seo_service import ping_google_sitemap
            
            # Ping Google sitemap (non-blocking)
            try:
                ping_google_sitemap()
            except Exception as e:
                logger.warning(f"Failed to ping Google sitemap: {e}")
        
    except Exception as e:
        logger.error(f"Error invalidating sitemap cache: {e}")


@receiver(post_delete, sender=ContentItem)
def invalidate_sitemap_cache_on_delete(sender, instance, **kwargs):
    """
    Automatically invalidate sitemap cache when content is deleted
    Also pings Google sitemap
    
    Note: Google Indexing API deletion notification is handled by 
    apps.media_manager.signals_seo to keep all SEO notifications in one place
    """
    try:
        # Invalidate home page sitemap cache
        cache.delete('sitemap_home_lastmod')
        
        # Invalidate content type specific cache
        content_type = instance.content_type
        cache.delete(f'sitemap_{content_type}_lastmod')
        
        # Invalidate general sitemap cache if exists
        cache.delete('sitemap_cache')
        
        logger.info(f"Invalidated sitemap cache after deletion of {content_type}")
        
        # Ping Google sitemap
        from apps.frontend_api.google_seo_service import ping_google_sitemap
        
        try:
            ping_google_sitemap()
        except Exception as e:
            logger.warning(f"Failed to ping Google sitemap: {e}")
        
    except Exception as e:
        logger.error(f"Error in post-delete sitemap signal: {e}")