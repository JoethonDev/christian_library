"""
Google Indexing Queue Service
Manages the queue for Google Indexing API submissions with:
- SEO + metadata validation
- Quota management (200 requests/day)
- Priority handling
- Error tracking
"""
import logging
from typing import Dict, Optional, List
from django.utils import timezone
from django.db import transaction
from datetime import timedelta

from apps.frontend_api.models_indexing import GoogleIndexingQueue, GoogleIndexingQuota
from apps.frontend_api.google_seo_service import (
    notify_google_indexing_api,
    get_absolute_content_url
)

logger = logging.getLogger(__name__)


# Priority levels for Google Indexing Queue
# Higher number = higher priority = processed first
PRIORITY_DELETION = 8      # Deletions (immediate)
PRIORITY_ARABIC = 10       # Arabic URLs (highest for normal indexing)
PRIORITY_STATIC = 7        # Static pages (home, search, lists)
PRIORITY_TAG = 6           # Tag pages
PRIORITY_ENGLISH = 5       # English URLs
PRIORITY_FEED = 4          # RSS feeds (lowest)


def get_priority_for_url(url_info: Dict) -> int:
    """
    Get priority based on URL type and language.
    
    Priority order:
    1. Deletions (8)
    2. Arabic content/pages (10)
    3. Static pages (7)
    4. Tag pages (6)
    5. English content/pages (5)
    6. RSS feeds (4)
    """
    if url_info.get('action') == 'URL_DELETED':
        return PRIORITY_DELETION
    
    language = url_info.get('language', 'ar')
    url_type = url_info.get('url_type', 'content')
    
    # Arabic always higher than English
    if language == 'ar':
        return PRIORITY_ARABIC
    
    # English URLs by type
    if url_type == 'static_page':
        return PRIORITY_STATIC
    elif url_type == 'tag_page':
        return PRIORITY_TAG
    elif url_type == 'rss_feed':
        return PRIORITY_FEED
    else:
        return PRIORITY_ENGLISH


class GoogleIndexingQueueService:
    """Service for managing Google Indexing API queue"""
    
    @staticmethod
    def validate_content_ready_for_indexing(content_item) -> Dict[str, any]:
        """
        Validate that content has both SEO metadata and basic metadata.
        
        Requirements for indexing:
        1. Content must be active
        2. Must have SEO metadata (seo_title, seo_description, etc.)
        3. Must have basic metadata (title, description)
        4. SEO processing status should be 'completed'
        
        Args:
content_item: ContentItem instance
        
        Returns:
            dict: {'ready': bool, 'reason': str, 'missing': list}
        """
        if not content_item.is_active:
            return {
                'ready': False,
                'reason': 'Content is not active',
                'missing': ['is_active']
            }
        
        missing_fields = []
        
        # Check basic metadata
        if not content_item.title_ar and not content_item.title_en:
            missing_fields.append('title')
        
        if not content_item.description_ar and not content_item.description_en:
            missing_fields.append('description')
        
        # Check SEO metadata
        seo_status = content_item.seo_processing_status
        
        if seo_status != 'completed':
            missing_fields.append(f'seo_processing (status: {seo_status})')
        
        if not content_item.has_seo_metadata():
            missing_fields.extend([
                'seo_title' if not (content_item.seo_title_ar or content_item.seo_title_en) else None,
                'seo_description' if not (content_item.seo_meta_description_ar or content_item.seo_meta_description_en) else None,
                'seo_keywords' if not (content_item.seo_keywords_ar or content_item.seo_keywords_en) else None,
            ])
            missing_fields = [f for f in missing_fields if f]  # Remove None values
        
        # Check structured data (optional but recommended)
        if not content_item.structured_data:
            logger.debug(f"Content {content_item.id} missing structured_data (optional)")
        
        if missing_fields:
            return {
                'ready': False,
                'reason': 'Missing required metadata',
                'missing': missing_fields
            }
        
        return {
            'ready': True,
            'reason': 'Content ready for indexing',
            'missing': []
        }
    
    @staticmethod
    def queue_for_indexing(
        content_item=None,
        url=None,
        url_type='content',
        action='URL_UPDATED',
        priority=None,
        force=False,
        language='ar',
        tag=None,
        **metadata
    ) -> Dict[str, any]:
        """
        Queue URL for Google indexing.
        Creates/updates GoogleIndexedUrl registry entry.
        
        Args:
            content_item: ContentItem instance (optional if url provided)
            url: Direct URL (optional if content_item provided)
            url_type: Type of URL ('content', 'static_page', 'tag_page', 'rss_feed')
            action: 'URL_UPDATED' or 'URL_DELETED'
            priority: Priority level (1-10, higher = more important). If None, auto-calculated
            force: Force queueing even if validation fails
            language: Language variant ('ar', 'en')
            tag: Tag instance (for tag pages)
            **metadata: Additional metadata
        
        Returns:
            dict: {'queued': bool, 'queue_item': GoogleIndexingQueue, 'indexed_url': GoogleIndexedUrl}
        """
        from apps.frontend_api.models_indexing import GoogleIndexedUrl
        
        # Get or build URL
        if not url:
            if not content_item:
                raise ValueError("Must provide either content_item or url")
            url = get_absolute_content_url(content_item, language=language)
        
        # Auto-calculate priority if not provided
        if priority is None:
            priority = get_priority_for_url({
                'action': action,
                'language': language,
                'url_type': url_type
            })
        
        # For deletions, skip validation
        if action == 'URL_DELETED':
            # Mark as deleted in registry
            indexed_url = GoogleIndexedUrl.objects.filter(url=url).first()
            if indexed_url:
                indexed_url.mark_as_deleted()
            
            # Create queue item
            queue_item = GoogleIndexingQueue.objects.create(
                content_item=None,  # Don't keep reference to deleted content
                url=url,
                action='URL_DELETED',
                priority=priority,
                status='pending'
            )
            
            logger.info(f"✓ Queued deletion: {url}")
            
            return {
                'queued': True,
                'queue_item': queue_item,
                'indexed_url': indexed_url,
                'validation': {'ready': True, 'reason': 'Deletion request', 'missing': []}
            }
        
        # For content URLs, validate if not forced
        validation_result = {'ready': True, 'reason': '', 'missing': []}
        
        if url_type == 'content' and content_item:
            validation_result = GoogleIndexingQueueService.validate_content_ready_for_indexing(content_item)
            
            if not validation_result['ready'] and not force:
                # Create registry entry as not_indexed
                indexed_url, created = GoogleIndexedUrl.objects.get_or_create(
                    url=url,
                    defaults={
                        'url_type': url_type,
                        'language': language,
                        'content_item': content_item,
                        'tag': tag,
                        'status': 'not_indexed',
                        'needs_reindex': False,
                        'last_error': f"{validation_result['reason']}. Missing: {', '.join(validation_result['missing'])}"
                    }
                )
                
                # Create queue item with 'invalid' status
                queue_item = GoogleIndexingQueue.objects.create(
                    content_item=content_item,
                    url=url,
                    action=action,
                    priority=priority,
                    status='invalid',
                    error_message=f"{validation_result['reason']}. Missing: {', '.join(validation_result['missing'])}"
                )
                
                logger.info(
                    f"⚠ Not ready for indexing: {url} | "
                    f"Reason: {validation_result['reason']} | "
                    f"Missing: {', '.join(validation_result['missing'])}"
                )
                
                return {
                    'queued': False,
                    'queue_item': queue_item,
                    'indexed_url': indexed_url,
                    'validation': validation_result
                }
        
        # Get or create registry entry
        indexed_url, created = GoogleIndexedUrl.objects.get_or_create(
            url=url,
            defaults={
                'url_type': url_type,
                'language': language,
                'content_item': content_item,
                'tag': tag,
                'status': 'not_indexed',
                'needs_reindex': False
            }
        )
        
        # Mark as pending in registry
        indexed_url.mark_as_pending()
        
        # Check if already queued
        existing = GoogleIndexingQueue.objects.filter(
            url=url,
            status__in=['pending', 'processing']
        ).first()
        
        if existing:
            logger.debug(f"URL already queued: {url}")
            return {
                'queued': True,
                'queue_item': existing,
                'indexed_url': indexed_url,
                'validation': validation_result,
                'already_queued': True
            }
        
        # Create new queue item
        queue_item = GoogleIndexingQueue.objects.create(
            content_item=content_item,
            url=url,
            action=action,
            priority=priority,
            status='pending'
        )
        
        logger.info(f"✓ Queued for indexing: {url} | Priority: {priority}")
        
        return {
            'queued': True,
            'queue_item': queue_item,
            'indexed_url': indexed_url,
            'validation': validation_result
        }
    
    @staticmethod
    def process_queue_batch(batch_size=10) -> Dict[str, any]:
        """
        Process a batch of queued items.
        
        Respects:
        - Daily quota (200 requests/day)
        - Priority order
        - Scheduled times
        - Retry limits
        
        Args:
            batch_size: Maximum number of items to process
        
        Returns:
            dict: {'processed': int, 'successful': int, 'failed': int, 'quota_exceeded': bool}
        """
        # Check quota
        if not GoogleIndexingQuota.has_quota_available():
            logger.warning("Google Indexing API daily quota exceeded (200/day)")
            
            # Mark pending items for tomorrow
            tomorrow = timezone.now() + timedelta(days=1)
            tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            
            GoogleIndexingQueue.objects.filter(
                status='pending'
            ).update(
                status='quota_exceeded',
                scheduled_for=tomorrow
            )
            
            return {
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'quota_exceeded': True
            }
        
        # Get available quota
        available_quota = GoogleIndexingQuota.get_remaining_quota()
        max_items = min(batch_size, available_quota)
        
        # Get pending items (prioritized, scheduled for now or past)
        now = timezone.now()
        pending_items = GoogleIndexingQueue.objects.filter(
            status__in=['pending', 'quota_exceeded']
        ).filter(
            models.Q(scheduled_for__lte=now) | models.Q(scheduled_for__isnull=True)
        ).order_by('-priority', 'created_at')[:max_items]
        
        processed = 0
        successful = 0
        failed = 0
        
        for item in pending_items:
            result = GoogleIndexingQueueService.process_queue_item(item)
            processed += 1
            
            if result['success']:
                successful += 1
            else:
                failed += 1
            
            # Stop if quota exceeded
            if result.get('quota_exceeded'):
                break
        
        logger.info(
            f"Processed {processed} indexing queue items: "
            f"{successful} successful, {failed} failed"
        )
        
        return {
            'processed': processed,
            'successful': successful,
            'failed': failed,
            'quota_exceeded': not GoogleIndexingQuota.has_quota_available()
        }
    
    @staticmethod
    def process_queue_item(queue_item: GoogleIndexingQueue) -> Dict[str, any]:
        """
        Process a single queue item.
        Updates GoogleIndexedUrl registry on success/failure.
        
        Args:
            queue_item: GoogleIndexingQueue instance
        
        Returns:
            dict: {'success': bool, 'error': str, 'quota_exceeded': bool}
        """
        from apps.frontend_api.models_indexing import GoogleIndexedUrl
        
        # Get registry entry
        indexed_url = GoogleIndexedUrl.objects.filter(url=queue_item.url).first()
        
        # Mark as processing
        queue_item.status = 'processing'
        queue_item.save(update_fields=['status', 'updated_at'])
        
        if indexed_url:
            indexed_url.mark_as_pending()
            indexed_url.increment_submission()
        
        # Submit to Google
        result = notify_google_indexing_api(queue_item.url, queue_item.action)
        
        # Handle result
        if result['success']:
            # Success - update both queue and registry
            queue_item.mark_as_success(response=result.get('response'))
            GoogleIndexingQuota.increment_usage(success=True)
            
            if indexed_url:
                indexed_url.mark_as_indexed(response=result.get('response'))
            
            logger.info(f"✓ Indexed successfully: {queue_item.url}")
            
            return {
                'success': True,
                'error': None,
                'quota_exceeded': False
            }
        
        # Handle different error types
        error_code = result.get('error_code', 'UNKNOWN')
        error_message = result.get('error', 'Unknown error')
        
        if error_code == 'QUOTA_EXCEEDED':
            # Quota exceeded - reschedule for tomorrow
            tomorrow = timezone.now() + timedelta(days=1)
            tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            
            queue_item.mark_as_quota_exceeded(next_available_time=tomorrow)
            
            logger.warning(f"Quota exceeded, rescheduled: {queue_item.url}")
            
            return {
                'success': False,
                'error': error_message,
                'quota_exceeded': True
            }
        
        # Other errors
        queue_item.increment_retry()
        
        if queue_item.retry_count >= queue_item.max_retries:
            # Max retries reached - mark as failed in both queue and registry
            queue_item.mark_as_failed(
                error_message=f"Max retries reached. {error_message}",
                error_code=error_code,
                response=result.get('response')
            )
            GoogleIndexingQuota.increment_usage(success=False)
            
            if indexed_url:
                indexed_url.mark_as_failed(
                    error_message=error_message,
                    error_code=error_code,
                    response=result.get('response')
                )
            
            logger.error(f"✗ Indexing failed (max retries): {queue_item.url} - {error_message}")
        else:
            # Retry later
            queue_item.status = 'pending'
            queue_item.error_message = error_message
            queue_item.error_code = error_code
            retry_delay = timedelta(minutes=30 * queue_item.retry_count)  # Exponential backoff
            queue_item.scheduled_for = timezone.now() + retry_delay
            queue_item.save(update_fields=['status', 'error_message', 'error_code', 'scheduled_for', 'updated_at'])
            
            logger.warning(
                f"Indexing failed (retry {queue_item.retry_count}/{queue_item.max_retries}): "
                f"{queue_item.url} - {error_message}"
            )
        
        return {
            'success': False,
            'error': error_message,
            'quota_exceeded': False
        }
    
    @staticmethod
    def get_queue_statistics() -> Dict[str, any]:
        """Get statistics about the indexing queue"""
        from django.db.models import Count, Q
        
        stats = GoogleIndexingQueue.objects.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            processing=Count('id', filter=Q(status='processing')),
            success=Count('id', filter=Q(status='success')),
            failed=Count('id', filter=Q(status='failed')),
            invalid=Count('id', filter=Q(status='invalid')),
            quota_exceeded=Count('id', filter=Q(status='quota_exceeded')),
        )
        
        quota = GoogleIndexingQuota.get_today_quota()
        
        return {
            **stats,
            'quota_used': quota.requests_used,
            'quota_remaining': GoogleIndexingQuota.get_remaining_quota(),
            'quota_date': quota.date,
        }
    
    @staticmethod
    def retry_failed_items(limit=50) -> Dict[str, any]:
        """Retry previously failed items"""
        failed_items = GoogleIndexingQueue.objects.filter(
            status='failed'
        ).order_by('-priority', 'processed_at')[:limit]
        
        reset_count = 0
        for item in failed_items:
            item.status = 'pending'
            item.retry_count = 0
            item.error_message = ''
            item.error_code = ''
            item.processed_at = None
            item.scheduled_for = None
            item.save(update_fields=[
                'status', 'retry_count', 'error_message', 'error_code', 
                'processed_at', 'scheduled_for', 'updated_at'
            ])
            reset_count += 1
        
        logger.info(f"Reset {reset_count} failed items for retry")
        
        return {
            'reset_count': reset_count
        }
    
    @staticmethod
    def revalidate_invalid_items() -> Dict[str, any]:
        """
        Revalidate items marked as invalid to see if they're now ready.
        Returns count of items that are now valid and queued.
        """
        from django.db.models import Q
        
        invalid_items = GoogleIndexingQueue.objects.filter(
            status='invalid',
            content_item__isnull=False
        ).select_related('content_item')
        
        revalidated = 0
        still_invalid = 0
        
        for item in invalid_items:
            validation = GoogleIndexingQueueService.validate_content_ready_for_indexing(item.content_item)
            
            if validation['ready']:
                # Now valid! Update status
                item.status = 'pending'
                item.error_message = ''
                item.error_code = ''
                item.save(update_fields=['status', 'error_message', 'error_code', 'updated_at'])
                revalidated += 1
                
                logger.info(f"✓ Item now valid and queued: {item.content_item.get_title()}")
            else:
                # Still invalid, update error message
                item.error_message = f"{validation['reason']}. Missing: {', '.join(validation['missing'])}"
                item.save(update_fields=['error_message', 'updated_at'])
                still_invalid += 1
        
        logger.info(f"Revalidated invalid items: {revalidated} now valid, {still_invalid} still invalid")
        
        return {
            'revalidated': revalidated,
            'still_invalid': still_invalid
        }


# Convenience function to import in signals
from django.db import models


def queue_content_for_google_indexing(content_item, action='URL_UPDATED', priority=5):
    """
    Convenience function to queue content for Google indexing.
    To be called from signals or views.
    """
    service = GoogleIndexingQueueService()
    return service.queue_for_indexing(content_item, action=action, priority=priority)
