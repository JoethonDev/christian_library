"""
Sitemap Auto-Update Signals
Automatically invalidate sitemap cache when content changes
Also notifies Google of updates via sitemap ping and Indexing API
"""
from django.db.models.signals import post_save, post_delete, pre_delete
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
        
        # Only notify Google for active content
        if instance.is_active:
            # Import here to avoid circular imports
            from apps.frontend_api.google_seo_service import ping_google_sitemap, notify_content_update
            
            # Ping Google sitemap (non-blocking)
            try:
                ping_google_sitemap()
            except Exception as e:
                logger.warning(f"Failed to ping Google sitemap: {e}")
            
            # Notify Google Indexing API (non-blocking)
            try:
                notify_content_update(instance)
            except Exception as e:
                logger.warning(f"Failed to notify Google Indexing API: {e}")
        
    except Exception as e:
        logger.error(f"Error invalidating sitemap cache: {e}")


# Store URL before deletion for Google notification
_deleted_content_urls = {}


@receiver(pre_delete, sender=ContentItem)
def store_deleted_content_url(sender, instance, **kwargs):
    """Store the URL before deletion so we can notify Google"""
    try:
        from apps.frontend_api.google_seo_service import get_absolute_content_url
        _deleted_content_urls[instance.id] = get_absolute_content_url(instance)
    except Exception as e:
        logger.error(f"Error storing deleted content URL: {e}")


@receiver(post_delete, sender=ContentItem)
def invalidate_sitemap_cache_on_delete(sender, instance, **kwargs):
    """
    Automatically invalidate sitemap cache when content is deleted
    Also notifies Google of the deletion
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
        from apps.frontend_api.google_seo_service import ping_google_sitemap, notify_google_indexing_api
        
        try:
            ping_google_sitemap()
        except Exception as e:
            logger.warning(f"Failed to ping Google sitemap: {e}")
        
        # Notify Google Indexing API about deletion
        try:
            if instance.id in _deleted_content_urls:
                url = _deleted_content_urls.pop(instance.id)
                notify_google_indexing_api(url, action='URL_DELETED')
        except Exception as e:
            logger.warning(f"Failed to notify Google Indexing API about deletion: {e}")
        
    except Exception as e:
        logger.error(f"Error in post-delete sitemap signal: {e}")