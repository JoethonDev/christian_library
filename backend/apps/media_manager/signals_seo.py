"""
SEO change detection signals.

Tracks SEO field updates and logs the content state for monitoring.
"""
import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.cache import cache

from apps.media_manager.models import ContentItem

logger = logging.getLogger(__name__)


# Cache key prefixes & TTL for cross-worker signal state
_SEO_TRACKER_PREFIX = 'seo_track:'
_DEL_TRACKER_PREFIX = 'del_track:'
_TRACKER_TTL = 60  # seconds — well beyond any pre/post signal gap

# SEO fields that should be tracked when changed
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
    Log SEO readiness when tracked fields change.
    """
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
    
    # Log readiness when SEO is complete.
    if should_queue:
        logger.info(
            f"SEO metadata ready: {instance.get_title()} | Changed: {', '.join(changed_fields)}"
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

