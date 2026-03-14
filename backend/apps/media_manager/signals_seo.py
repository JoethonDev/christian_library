"""
SEO Change Detection Signals
Detects changes to SEO-specific fields and queues Google Indexing API notifications.
Only queues when SEO metadata is complete and ready for indexing.
Also handles content deletion notifications.
"""
import logging

from django.db.models.signals import post_save, pre_save, pre_delete, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.media_manager.models import ContentItem

logger = logging.getLogger(__name__)


# Cache key prefixes & TTL for cross-worker signal state
_SEO_TRACKER_PREFIX = 'seo_track:'
_DEL_TRACKER_PREFIX = 'del_track:'
_TRACKER_TTL = 60  # seconds — well beyond any pre/post signal gap

# SEO fields that should trigger Google notification when changed
SEO_FIELDS = [
    'seo_title_ar',
    'seo_title_en',
    'seo_meta_description_ar',
    'seo_meta_description_en',
    'seo_keywords_ar',
    'seo_keywords_en',
    'structured_data',
]


@receiver(pre_save, sender=ContentItem)
def track_seo_fields_before_save(sender, instance, **kwargs):
    """
    Store current SEO field values before save to detect changes
    Only tracks for existing instances (not new creations)
    """
    if instance.pk:  # Only for updates, not creates
        try:
            # Get current values from database
            old_instance = ContentItem.objects.filter(pk=instance.pk).only(*SEO_FIELDS).first()
            
            if old_instance:
                # Store old SEO field values in shared cache (safe across workers)
                cache.set(
                    f'{_SEO_TRACKER_PREFIX}{instance.pk}',
                    {field: getattr(old_instance, field) for field in SEO_FIELDS},
                    timeout=_TRACKER_TTL,
                )
        except ContentItem.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error tracking SEO fields for ContentItem {instance.pk}: {e}")


@receiver(post_save, sender=ContentItem)
def notify_google_on_seo_change(sender, instance, created, **kwargs):
    """
    Queue content for Google Indexing when SEO metadata is ready.
    
    Triggers on:
    - SEO field updates (seo_title_*, seo_meta_description_*, seo_keywords_*, structured_data)
    - Only if SEO processing status is 'completed'
    - Only if all required metadata is present
    
    Does NOT trigger on:
    - New content creation without SEO (will queue once SEO is done)
    - Non-SEO field updates (e.g., view_count, is_active, etc.)
    - Updates that don't change SEO values
    
    Uses queue system with validation to ensure:
    - Only complete content is submitted to Google
    - Daily quota limits are respected (200/day)
    - Errors are tracked and retryable
    """
    # Import here to avoid circular imports
    from apps.frontend_api.services.google_indexing_queue_service import (
        GoogleIndexingQueueService
    )
    
    # Only process active content
    if not instance.is_active:
        logger.debug(f"Skipping inactive content: {instance.get_title()}")
        return
    
    should_queue = False
    changed_fields = []
    priority = 5  # Default priority
    
    if created:
        # New content - check if SEO is ready
        if instance.seo_processing_status == 'completed' and instance.has_seo_metadata():
            should_queue = True
            changed_fields = ['NEW_CONTENT_WITH_SEO']
            priority = 7  # Higher priority for new content
            logger.info(f"New content with complete SEO: {instance.get_title()}")
        else:
            logger.info(
                f"New content without complete SEO: {instance.get_title()} "
                f"(status: {instance.seo_processing_status}) - will queue once SEO is done"
            )
            return
    
    else:
        # Update - check if SEO fields changed
        cache_key = f'{_SEO_TRACKER_PREFIX}{instance.pk}'
        old_values = cache.get(cache_key)
        
        if old_values is not None:
            cache.delete(cache_key)
            
            for field in SEO_FIELDS:
                old_val = old_values.get(field)
                new_val = getattr(instance, field)
                
                # Handle structured_data (JSON) comparison
                if field == 'structured_data':
                    if str(old_val) != str(new_val):
                        changed_fields.append(field)
                else:
                    if old_val != new_val:
                        changed_fields.append(field)
            
            if changed_fields:
                # SEO changed - check if now complete
                if instance.seo_processing_status == 'completed' and instance.has_seo_metadata():
                    should_queue = True
                    priority = 6  # Medium-high priority for SEO updates
                    logger.info(
                        f"SEO updated and complete: {instance.get_title()} "
                        f"| Changed: {', '.join(changed_fields)}"
                    )
                else:
                    logger.info(
                        f"SEO updated but not complete: {instance.get_title()} "
                        f"| Status: {instance.seo_processing_status}"
                    )
                    return
    
    # Queue for Google indexing if ready
    if should_queue:
        try:
            result = GoogleIndexingQueueService.queue_for_indexing(
                content_item=instance,
                action='URL_UPDATED',
                priority=priority
            )
            
            if result['queued']:
                if result.get('already_queued'):
                    logger.debug(f"Already queued: {instance.get_title()}")
                else:
                    logger.info(
                        f"✓ Queued for Google indexing: {instance.get_title()} "
                        f"| Priority: {priority} | Changed: {', '.join(changed_fields)}"
                    )
            else:
                # Not ready yet
                validation = result.get('validation', {})
                logger.info(
                    f"⚠ Not ready for indexing: {instance.get_title()} "
                    f"| Reason: {validation.get('reason')} "
                    f"| Missing: {', '.join(validation.get('missing', []))}"
                )
        
        except Exception as e:
            logger.error(f"Error queuing content for indexing: {e}", exc_info=True)
    
    else:
        # Non-SEO update - skip
        logger.debug(
            f"Non-SEO update for {instance.get_title()} - skipping indexing queue"
        )


@receiver(post_save, sender=ContentItem)
def log_seo_generation_status(sender, instance, created, **kwargs):
    """
    Log SEO processing status for monitoring and debugging
    Helps track which content has SEO metadata and which needs generation
    """
    try:
        # Only log for active content
        if not instance.is_active:
            return
        
        has_seo = instance.has_seo_metadata()
        status = instance.seo_processing_status
        
        if created:
            if has_seo:
                logger.info(
                    f"✓ New content with SEO metadata: {instance.get_title()} "
                    f"| Status: {status}"
                )
            else:
                logger.info(
                    f"⚠ New content WITHOUT SEO metadata: {instance.get_title()} "
                    f"| Status: {status}"
                )
        
        elif status == 'completed' and has_seo:
            # SEO successfully generated/updated
            logger.debug(
                f"✓ SEO metadata present: {instance.get_title()} "
                f"| AR Title: {len(instance.seo_title_ar or '')} chars "
                f"| EN Title: {len(instance.seo_title_en or '')} chars"
            )
    
    except Exception as e:
        logger.error(f"Error logging SEO generation status: {e}")

@receiver(pre_delete, sender=ContentItem)
def store_deleted_content_url(sender, instance, **kwargs):
    """
    Store the URL before deletion so we can notify Google
    Must happen in pre_delete because we need the instance to still exist
    to generate its URL
    """
    try:
        from apps.frontend_api.google_seo_service import get_absolute_content_url
        
        # Store URL in shared cache for post_delete handler (safe across workers)
        cache.set(
            f'{_DEL_TRACKER_PREFIX}{instance.id}',
            get_absolute_content_url(instance),
            timeout=_TRACKER_TTL,
        )
        
        logger.debug(f"Stored URL for deletion notification: {instance.get_title()}")
    
    except Exception as e:
        logger.error(f"Error storing deleted content URL: {e}")


@receiver(post_delete, sender=ContentItem)
def notify_google_on_content_deletion(sender, instance, **kwargs):
    """
    Queue content deletion notification for Google Indexing API.
    This ensures Google removes the URL from search results quickly.
    """
    from apps.frontend_api.services.google_indexing_queue_service import (
        GoogleIndexingQueueService
    )
    
    try:
        # Get stored URL (from pre_delete, any worker)
        cache_key = f'{_DEL_TRACKER_PREFIX}{instance.id}'
        url = cache.get(cache_key)
        if url:
            cache.delete(cache_key)
        
        if not url:
            logger.warning(f"No URL stored for deleted content: {instance.id}")
            return
        
        # Queue deletion notification (high priority)
        result = GoogleIndexingQueueService.queue_for_indexing(
            content_item=instance,
            action='URL_DELETED',
            priority=8  # High priority for deletions
        )
        
        if result['queued']:
            logger.info(
                f"✓ Queued deletion for Google: {instance.get_title()} "
                f"| Type: {instance.content_type} | URL: {url}"
            )
        else:
            logger.warning(
                f"Failed to queue deletion: {instance.get_title()} "
                f"| Error: {result.get('validation', {}).get('reason')}"
            )
    
    except Exception as e:
        logger.error(f"Error queuing content deletion for indexing: {e}", exc_info=True)