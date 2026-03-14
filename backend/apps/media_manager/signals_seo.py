"""
SEO Change Detection Signals
Detects changes to SEO-specific fields and triggers Google Indexing API notifications
Only notifies Google when SEO metadata actually changes, not on every save
Also handles content deletion notifications
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
    Notify Google Indexing API when SEO metadata changes
    
    Triggers on:
    - New content creation (created=True)
    - SEO field updates (any of: seo_title_*, seo_meta_description_*, seo_keywords_*, structured_data)
    
    Does NOT trigger on:
    - Non-SEO field updates (e.g., view_count, is_active, etc.)
    - Updates that don't change SEO values
    """
    # Only notify for active content
    if not instance.is_active:
        return
    
    should_notify = False
    changed_fields = []
    
    if created:
        # Always notify for new content
        should_notify = True
        changed_fields = ['NEW_CONTENT']
        logger.info(f"New content created: {instance.get_title()} - will notify Google")
    
    else:
        # Check whether cached pre-save SEO values exist (set by pre_save in any worker)
        cache_key = f'{_SEO_TRACKER_PREFIX}{instance.pk}'
        old_values = cache.get(cache_key)
        if old_values is not None:
            cache.delete(cache_key)
        
        for field in SEO_FIELDS:
            old_val = old_values.get(field)
            new_val = getattr(instance, field)
            
            # Handle structured_data (JSON) comparison carefully
            if field == 'structured_data':
                # Compare as strings to avoid dict ordering issues
                if str(old_val) != str(new_val):
                    changed_fields.append(field)
            else:
                # Direct comparison for other fields
                if old_val != new_val:
                    changed_fields.append(field)
        
        if changed_fields:
            should_notify = True
            logger.info(f"SEO fields changed for {instance.get_title()}: {', '.join(changed_fields)}")
    
    # Notify Google if SEO changed
    if should_notify:
        try:
            from apps.frontend_api.google_seo_service import notify_content_update
            
            success = notify_content_update(instance)
            
            if success:
                logger.info(
                    f"✓ Google notified about SEO changes for: {instance.get_title()} "
                    f"| Type: {instance.content_type} "
                    f"| Changed: {', '.join(changed_fields)}"
                )
            else:
                # Don't log as error - might just be credentials not configured yet
                logger.debug(
                    f"Google Indexing API not notified (may not be configured) "
                    f"for: {instance.get_title()}"
                )
        
        except Exception as e:
            logger.warning(f"Failed to notify Google Indexing API: {e}")
    
    else:
        # Non-SEO update - skip notification
        logger.debug(
            f"Non-SEO update for {instance.get_title()} - skipping Google notification"
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
    Notify Google Indexing API when content is deleted
    This ensures Google removes the URL from search results quickly
    """
    try:
        # Get stored URL (from pre_delete, any worker)
        cache_key = f'{_DEL_TRACKER_PREFIX}{instance.id}'
        url = cache.get(cache_key)
        if url:
            cache.delete(cache_key)
        
        if not url:
            logger.warning(f"No URL stored for deleted content: {instance.id}")
            return
        
        # Notify Google about deletion
        from apps.frontend_api.google_seo_service import notify_google_indexing_api
        
        success = notify_google_indexing_api(url, action='URL_DELETED')
        
        if success:
            logger.info(
                f"✓ Google notified about content deletion: {instance.get_title()} "
                f"| Type: {instance.content_type} "
                f"| URL: {url}"
            )
        else:
            logger.debug(
                f"Google Indexing API not notified about deletion (may not be configured) "
                f"for: {instance.get_title()}"
            )
    
    except Exception as e:
        logger.warning(f"Failed to notify Google about content deletion: {e}")