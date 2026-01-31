"""
Phase 4: Cache Invalidation Signals

This module implements Django signals to automatically invalidate relevant caches
when content or tags are created, updated, or deleted.
"""

from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from apps.media_manager.models import ContentItem, Tag
from core.utils.cache_utils import CacheInvalidation
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ContentItem)
def invalidate_content_caches_on_save(sender, instance, created, **kwargs):
    """Invalidate relevant caches when ContentItem is saved"""
    try:
        # Invalidate content statistics and related content caches
        CacheInvalidation.invalidate_content_stats(str(instance.id))
        
        logger.info(f"Cache invalidation triggered by ContentItem save: {instance.id} ({instance.content_type})")
    except Exception as e:
        logger.error(f"Cache invalidation error on ContentItem save: {e}")


@receiver(post_delete, sender=ContentItem)  
def invalidate_content_caches_on_delete(sender, instance, **kwargs):
    """Invalidate relevant caches when ContentItem is deleted"""
    try:
        # Invalidate content statistics and related content caches
        CacheInvalidation.invalidate_content_stats(str(instance.id))
        
        logger.info(f"Cache invalidation triggered by ContentItem delete: {instance.id} ({instance.content_type})")
    except Exception as e:
        logger.error(f"Cache invalidation error on ContentItem delete: {e}")


@receiver(post_save, sender=Tag)
def invalidate_tag_caches_on_save(sender, instance, created, **kwargs):
    """Invalidate tag-related caches when Tag is saved"""
    try:
        # Invalidate tag-related caches (popular tags, home stats)
        CacheInvalidation.invalidate_tag_caches()
        
        logger.info(f"Cache invalidation triggered by Tag save: {instance.id} ({instance.name_ar})")
    except Exception as e:
        logger.error(f"Cache invalidation error on Tag save: {e}")


@receiver(post_delete, sender=Tag)
def invalidate_tag_caches_on_delete(sender, instance, **kwargs):
    """Invalidate tag-related caches when Tag is deleted"""
    try:
        # Invalidate tag-related caches (popular tags, home stats)
        CacheInvalidation.invalidate_tag_caches()
        
        logger.info(f"Cache invalidation triggered by Tag delete: {instance.id} ({instance.name_ar})")
    except Exception as e:
        logger.error(f"Cache invalidation error on Tag delete: {e}")


@receiver(m2m_changed, sender=ContentItem.tags.through)
def invalidate_content_tag_caches(sender, instance, action, pk_set, **kwargs):
    """Invalidate caches when ContentItem-Tag relationships change"""
    if action in ['post_add', 'post_remove', 'post_clear']:
        try:
            # Invalidate both content and tag caches when relationships change
            CacheInvalidation.invalidate_content_stats(str(instance.id))
            CacheInvalidation.invalidate_tag_caches()
            
            logger.info(f"Cache invalidation triggered by M2M change: {instance.id} action={action}")
        except Exception as e:
            logger.error(f"Cache invalidation error on M2M change: {e}")


# Additional signals for metadata changes
from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta

@receiver(post_save, sender=VideoMeta)
@receiver(post_save, sender=AudioMeta)
@receiver(post_save, sender=PdfMeta)
def invalidate_content_caches_on_meta_save(sender, instance, **kwargs):
    """Invalidate content caches when metadata is updated"""
    try:
        content_item = instance.content_item
        # Only invalidate content stats when processing status changes (affects dashboard)
        CacheInvalidation.invalidate_content_stats(str(content_item.id))
        
        logger.info(f"Cache invalidation triggered by {sender.__name__} save: {content_item.id}")
    except Exception as e:
        logger.error(f"Cache invalidation error on metadata save: {e}")