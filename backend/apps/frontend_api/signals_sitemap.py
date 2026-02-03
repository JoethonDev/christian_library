"""
Sitemap Auto-Update Signals
Automatically invalidate sitemap cache when content changes
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.media_manager.models import ContentItem
import logging

logger = logging.getLogger(__name__)


@receiver([post_save, post_delete], sender=ContentItem)
def invalidate_sitemap_cache(sender, instance, **kwargs):
    """
    Automatically invalidate sitemap cache when content is created, updated, or deleted
    This ensures sitemaps are always up-to-date without manual intervention
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
        
    except Exception as e:
        logger.error(f"Error invalidating sitemap cache: {e}")