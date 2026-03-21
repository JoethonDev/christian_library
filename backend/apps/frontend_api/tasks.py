"""
Celery tasks for frontend_api app
"""
import logging
from celery import shared_task
from django.apps import apps
from django.utils import timezone
from django.core.cache import cache
from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
from apps.frontend_api.services.url_generator_service import get_url_generator
from apps.frontend_api.models_indexing import GoogleIndexedUrl
from apps.frontend_api.google_seo_service import ping_google_sitemap

logger = logging.getLogger(__name__)

# Lock key for preventing concurrent re-indexing
REINDEX_LOCK_KEY = 'google_reindex_lock'
REINDEX_LOCK_TIMEOUT = 3600  # 1 hour

# Lock key for indexing queue processing
INDEXING_QUEUE_LOCK_KEY = 'google_indexing_queue_lock'
INDEXING_QUEUE_LOCK_TIMEOUT = 300  # 5 minutes


def get_googlereindexingtask_model():
    """Get GoogleReindexingTask model dynamically to avoid circular imports"""
    return apps.get_model('frontend_api', 'GoogleReindexingTask')


@shared_task(bind=True, max_retries=0, time_limit=3600)
def reindex_website_google(self, task_id, content_type=None, include_sitemap=True, force=False):
    """
    Re-index website content on Google Search Console.
    
    Now uses GoogleIndexingQueue system for actual submission.
    This task queues URLs; processing happens in process_google_indexing_queue.
    
    Args:
        task_id: UUID of GoogleReindexingTask
        content_type: Type of content to re-index (optional)
        include_sitemap: Whether to ping sitemap after completion
        force: Force re-indexing of ALL URLs (even if already indexed)
    """
    GoogleReindexingTask = get_googlereindexingtask_model()
    
    # Acquire lock to prevent concurrent re-indexing
    lock_acquired = cache.add(REINDEX_LOCK_KEY, self.request.id, REINDEX_LOCK_TIMEOUT)
    if not lock_acquired:
        logger.error(f"Could not acquire lock for re-indexing task {task_id}")
        return {
            'success': False,
            'error': 'Another re-indexing operation is in progress'
        }
    
    try:
        # Get the task
        task = GoogleReindexingTask.objects.get(id=task_id)
        
        # Mark as in progress
        task.status = 'in_progress'
        task.started_at = timezone.now()
        task.save(update_fields=['status', 'started_at', 'updated_at'])
        
        logger.info(f"Starting re-indexing task {task_id} | Content type: {content_type} | Force: {force}")
        
        # Initialize service
        service = GoogleReindexingService()
        
        # Get URLs to index (from URL generator + registry filtering)        
        url_generator = get_url_generator()
        all_urls = url_generator.get_all_urls(content_type=content_type, include_static=True)
        
        # Filter based on force flag
        urls_to_queue = []
        
        if force:
            # Force: queue ALL URLs
            urls_to_queue = all_urls
            # Mark all existing registry entries for re-index
            GoogleIndexedUrl.objects.filter(
                url__in=[u['url'] for u in all_urls]
            ).update(needs_reindex=True)
            logger.info(f"Force re-index: queueing all {len(urls_to_queue)} URLs")
        else:
            # Normal: only queue not_indexed, failed, or needing re-index
            for url_info in all_urls:
                indexed_url = GoogleIndexedUrl.objects.filter(url=url_info['url']).first()
                if not indexed_url or indexed_url.status in ['not_indexed', 'failed'] or indexed_url.needs_reindex:
                    urls_to_queue.append(url_info)
            
            logger.info(f"Normal re-index: queueing {len(urls_to_queue)} URLs (out of {len(all_urls)} total)")
        
        if not urls_to_queue:
            logger.info(f"No URLs to queue for re-indexing task {task_id}")
            task.status = 'completed'
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'completed_at', 'updated_at'])
            return {
                'success': True,
                'message': 'No URLs need re-indexing',
                'total': 0,
                'queued': 0,
                'skipped': 0
            }
        
        # Update total URLs
        task.total_urls = len(urls_to_queue)
        task.save(update_fields=['total_urls', 'updated_at'])
        
        # Queue URLs via GoogleIndexingQueue
        queued_count, skipped_count = service.queue_urls_for_reindexing(
            urls_to_queue, 
            task_id,
            force=force
        )
        
        # Update task
        task.submitted_urls = len(urls_to_queue)
        task.successful_urls = queued_count
        task.failed_urls = skipped_count
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.save(update_fields=[
            'submitted_urls', 'successful_urls', 'failed_urls',
            'status', 'completed_at', 'updated_at'
        ])
        
        logger.info(
            f"Re-indexing task {task_id} completed | "
            f"Queued: {queued_count}, Skipped: {skipped_count}"
        )
        
        # Ping sitemap if requested
        if include_sitemap:
            try:
                logger.info(f"Pinging Google sitemap for task {task_id}")
                ping_google_sitemap()
            except Exception as e:
                logger.error(f"Error pinging sitemap: {e}")
        
        # Send notification email
        try:
            send_reindex_completion_email(task)
        except Exception as e:
            logger.error(f"Error sending completion email: {e}")
        
        return {
            'success': True,
            'task_id': str(task_id),
            'total': task.total_urls,
            'queued': queued_count,
            'skipped': skipped_count
        }
        
    except GoogleReindexingTask.DoesNotExist:
        logger.error(f"Re-indexing task {task_id} not found")
        return {
            'success': False,
            'error': 'Task not found'
        }
    except Exception as e:
        logger.exception(f"Error in re-indexing task {task_id}: {e}")
        
        # Mark task as failed
        try:
            task = GoogleReindexingTask.objects.get(id=task_id)
            task.mark_as_failed(str(e))
        except:
            pass
        
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Release lock
        cache.delete(REINDEX_LOCK_KEY)


def send_reindex_completion_email(task):
    """
    Send completion email to task initiator.
    
    Args:
        task: GoogleReindexingTask instance
    """
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings
    from django.contrib.sites.models import Site
    
    if not task.initiated_by or not task.initiated_by.email:
        logger.warning(f"Cannot send email for task {task.id}: no user email")
        return
    
    # Get site URL
    try:
        current_site = Site.objects.get_current()
        site_url = f'https://{current_site.domain}'
    except:
        site_url = 'https://yoursite.com'  # Fallback
    
    # Calculate duration
    duration = None
    if task.started_at and task.completed_at:
        duration_seconds = (task.completed_at - task.started_at).total_seconds()
        duration_minutes = int(duration_seconds / 60)
        duration = f"{duration_minutes} minutes" if duration_minutes > 0 else "less than a minute"
    
    # Determine status for subject
    if task.status == 'completed':
        if task.failed_urls == 0:
            status_text = 'Success'
        elif task.failed_urls < task.total_urls * 0.1:
            status_text = 'Partial Success'
        else:
            status_text = 'Completed with Errors'
    else:
        status_text = 'Failed'
    
    subject = f'Google Re-indexing {status_text} - Christian Library'
    
    # Prepare context
    context = {
        'task': task,
        'user': task.initiated_by,
        'status_text': status_text,
        'error_summary': task.get_error_summary(),
        'success_rate': task.get_success_rate(),
        'site_url': site_url,
        'duration': duration,
    }
    
    # Render email templates
    try:
        html_message = render_to_string('emails/reindex_complete.html', context)
        text_message = render_to_string('emails/reindex_complete.txt', context)
    except Exception as e:
        logger.error(f"Error rendering email templates: {e}")
        # Fallback to plain text
        text_message = f"""
Google Re-indexing Task Completed

Status: {status_text}
Content Type: {task.content_type}
Total URLs: {task.total_urls}
Successful: {task.successful_urls}
Failed: {task.failed_urls}
Success Rate: {task.get_success_rate()}%

Started: {task.started_at}
Completed: {task.completed_at}
        """
        html_message = None
    
    # Send email
    try:
        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@christianlibrary.com',
            recipient_list=[task.initiated_by.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Sent completion email for task {task.id} to {task.initiated_by.email}")
    except Exception as e:
        logger.error(f"Error sending email: {e}")


# ============================================================================
# Google Indexing Queue Tasks
# ============================================================================

@shared_task(bind=True, max_retries=3)
def process_google_indexing_queue(self, batch_size=10):
    """
    Process pending items in the Google Indexing Queue.
    
    This task:
    1. Checks daily quota (200 requests/day max)
    2. Processes pending items by priority
    3. Handles rate limiting and errors
    4. Reschedules items if quota exceeded
    5. Retries failed items with exponential backoff
    
    Args:
        batch_size: Max number of items to process (default: 10)
    
    Returns:
        dict: Processing statistics
    """
    from apps.frontend_api.services.google_indexing_queue_service import (
        GoogleIndexingQueueService
    )
    
    # Acquire lock to prevent concurrent processing
    lock_acquired = cache.add(INDEXING_QUEUE_LOCK_KEY, self.request.id, INDEXING_QUEUE_LOCK_TIMEOUT)
    if not lock_acquired:
        logger.warning("Another indexing queue task is already running")
        return {
            'success': False,
            'error': 'Lock not acquired'
        }
    
    try:
        logger.info(f"Processing Google Indexing Queue (batch_size={batch_size})")
        
        # Process batch
        result = GoogleIndexingQueueService.process_queue_batch(batch_size=batch_size)
        
        logger.info(
            f"Indexing queue batch completed: "
            f"{result['processed']} processed, "
            f"{result['successful']} successful, "
            f"{result['failed']} failed"
        )
        
        return {
            'success': True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Error processing indexing queue: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Release lock
        cache.delete(INDEXING_QUEUE_LOCK_KEY)


@shared_task
def revalidate_invalid_indexing_items():
    """
    Revalidate items marked as invalid to check if they're now ready.
    
    This task checks items that were previously invalid due to missing
    SEO/metadata to see if they're now complete and ready for indexing.
    
    Should be run periodically (e.g., every hour) to catch items whose
    SEO metadata was generated after initial queueing.
    
    Returns:
        dict: Revalidation statistics
    """
    from apps.frontend_api.services.google_indexing_queue_service import (
        GoogleIndexingQueueService
    )
    
    try:
        logger.info("Revalidating invalid indexing queue items")
        
        result = GoogleIndexingQueueService.revalidate_invalid_items()
        
        logger.info(
            f"Revalidation complete: "
            f"{result['revalidated']} now valid, "
            f"{result['still_invalid']} still invalid"
        )
        
        return {
            'success': True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Error revalidating indexing items: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def retry_failed_indexing_items(limit=50):
    """
    Retry previously failed indexing items.
    
    This task resets failed items to pending status so they can be retried.
    Useful for recovering from temporary API failures or configuration issues.
    
    Args:
        limit: Maximum number of failed items to retry (default: 50)
    
    Returns:
        dict: Retry statistics
    """
    from apps.frontend_api.services.google_indexing_queue_service import (
        GoogleIndexingQueueService
    )
    
    try:
        logger.info(f"Retrying failed indexing items (limit={limit})")
        
        result = GoogleIndexingQueueService.retry_failed_items(limit=limit)
        
        logger.info(f"Reset {result['reset_count']} failed items for retry")
        
        return {
            'success': True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Error retrying failed indexing items: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def cleanup_old_indexing_queue_items(days=30):
    """
    Clean up old completed/failed indexing queue items.
    
    Removes items older than specified days to prevent database bloat.
    Only removes items with final status (success/failed).
    
    Args:
        days: Remove items older than this many days (default: 30)
    
    Returns:
        dict: Cleanup statistics
    """
    from apps.frontend_api.models_indexing import GoogleIndexingQueue
    from datetime import timedelta
    
    try:
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Only delete completed or failed items
        deleted_count = GoogleIndexingQueue.objects.filter(
            status__in=['success', 'failed'],
            processed_at__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"Cleaned up {deleted_count} old indexing queue items (older than {days} days)")
        
        return {
            'success': True,
            'deleted_count': deleted_count
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up indexing queue: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
