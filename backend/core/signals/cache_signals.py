"""
Cache invalidation signals for automatic cache management.
"""

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.core.cache import cache
from core.utils.cache_utils import cache_invalidator
import logging

from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
from apps.users.models import User

logger = logging.getLogger(__name__)


# Content Item Signals

@receiver(post_save, sender=ContentItem)
def invalidate_content_cache_on_save(sender, instance, created, **kwargs):
    """Invalidate content-related caches when content is saved"""
    logger.debug(f"Invalidating content caches for content item {instance.id}")
    
    # Invalidate content-specific caches
    cache_invalidator.invalidate_content_caches(instance.content_type)
    
    # Module functionality has been removed
    # if instance.module:
    #     cache_invalidator.invalidate_course_caches(instance.module.course.id)
    
    # Clear general navigation caches
    cache_invalidator.invalidate_navigation_caches()


@receiver(post_delete, sender=ContentItem)
def invalidate_content_cache_on_delete(sender, instance, **kwargs):
    """Invalidate content-related caches when content is deleted"""
    logger.debug(f"Invalidating content caches after deletion of content item {instance.id}")
    
    cache_invalidator.invalidate_content_caches()
    
    # Module functionality has been removed
    # if instance.module:
    #     cache_invalidator.invalidate_course_caches(instance.module.course.id)


# Media Meta Signals

@receiver(post_save, sender=VideoMeta)
@receiver(post_save, sender=AudioMeta)
@receiver(post_save, sender=PdfMeta)
def invalidate_media_cache_on_meta_save(sender, instance, created, **kwargs):
    """Invalidate content cache when media metadata changes"""
    content_item = instance.content_item
    logger.debug(f"Invalidating content cache for meta update on content {content_item.id}")
    
    # Clear content-specific cache
    cache_key = f"content_item_{content_item.id}_ar"
    cache.delete(cache_key)
    cache_key = f"content_item_{content_item.id}_en" 
    cache.delete(cache_key)
    
    # Clear processing status cache
    cache.delete(f"media_processing_status_{content_item.id}")



# Tag Signals

@receiver(post_save, sender=Tag)
def invalidate_tag_cache_on_save(sender, instance, created, **kwargs):
    """Invalidate tag-related caches when tag is saved"""
    logger.debug(f"Invalidating tag caches for tag {instance.id}")
    
    # Clear tag list caches
    cache.delete('tag_list_True_ar')  # Popular tags
    cache.delete('tag_list_True_en')
    cache.delete('tag_list_False_ar')  # All tags
    cache.delete('tag_list_False_en')
    
    # Clear navigation caches
    cache_invalidator.invalidate_navigation_caches()


@receiver(post_delete, sender=Tag)
def invalidate_tag_cache_on_delete(sender, instance, **kwargs):
    """Invalidate tag-related caches when tag is deleted"""
    logger.debug(f"Invalidating tag caches after deletion of tag {instance.id}")
    
    cache.delete('tag_list_True_ar')
    cache.delete('tag_list_True_en') 
    cache.delete('tag_list_False_ar')
    cache.delete('tag_list_False_en')
    cache_invalidator.invalidate_navigation_caches()


# User Signals

@receiver(post_save, sender=User)
def invalidate_user_cache_on_save(sender, instance, created, **kwargs):
    """Invalidate user-related caches when user is saved"""
    logger.debug(f"User {instance.id} saved - per-user caching disabled")
    
    # Note: Per-user caching removed in Phase 4 refactoring
    # Use whole-view caching with @cache_page decorator instead
    
    # If content manager status changed, clear content manager cache
    if hasattr(instance, '_state') and not instance._state.adding:
        # Check if is_content_manager changed
        try:
            old_instance = User.objects.get(pk=instance.pk)
            if old_instance.is_content_manager != instance.is_content_manager:
                cache.delete('content_managers')
        except User.DoesNotExist:
            pass


@receiver(post_delete, sender=User)
def invalidate_user_cache_on_delete(sender, instance, **kwargs):
    """Invalidate user-related caches when user is deleted"""
    logger.debug(f"User {instance.id} deleted - per-user caching disabled")
    
    # Note: Per-user caching removed in Phase 4 refactoring
    # Use whole-view caching with @cache_page decorator instead


# Bulk Operations Signals

@receiver(pre_delete, sender=ContentItem)
def prepare_content_deletion(sender, instance, **kwargs):
    """Prepare for content deletion by storing related IDs"""
    # Module functionality has been removed
    # if instance.module:
    #     instance._cached_module_id = instance.module.id
    #     instance._cached_course_id = instance.module.course.id
    pass


# Custom signal for cache warming

def warm_critical_caches():
    """Warm up critical application caches"""
    from core.utils.cache_utils import CacheMonitoring
    
    logger.info("Starting cache warm-up process")
    try:
        CacheMonitoring.warm_up_caches()
        logger.info("Cache warm-up completed successfully")
    except Exception as e:
        logger.error(f"Cache warm-up failed: {str(e)}")


# Signal for application startup cache warming
from django.core.signals import request_started

@receiver(request_started)
def warm_caches_on_first_request(sender, **kwargs):
    """Warm caches on first request to improve performance"""
    cache_key = 'caches_warmed'
    if not cache.get(cache_key):
        warm_critical_caches()
        cache.set(cache_key, True, 3600)  # Don't warm again for 1 hour