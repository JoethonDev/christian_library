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
        content_item, 
        action='URL_UPDATED', 
        priority=5, 
        force=False
    ) -> Dict[str, any]:
        """
        Queue content for Google indexing.
        
        Args:
            content_item: ContentItem instance
            action: 'URL_UPDATED' or 'URL_DELETED'
            priority: Priority level (1-10, higher = more important)
            force: Force queueing even if validation fails
        
        Returns:
            dict: {'queued': bool, 'queue_item': GoogleIndexingQueue, 'validation': dict}
        """
        # For deletions, skip validation
        if action == 'URL_DELETED':
            url = get_absolute_content_url(content_item)
            
            # Create queue item
            queue_item = GoogleIndexingQueue.objects.create(
                content_item=None,  # Don't keep reference to deleted content
                url=url,
                action=action,
                priority=priority,
                status='pending'
            )
            
            logger.info(f"Queued deletion for indexing: {url}")
            
            return {
                'queued': True,
                'queue_item': queue_item,
                'validation': {'ready': True, 'reason': 'Deletion request', 'missing': []}
            }
        
        # For updates, validate content
        validation = GoogleIndexingQueueService.validate_content_ready_for_indexing(content_item)
        
        if not validation['ready'] and not force:
            logger.info(
                f"Content {content_item.id} not ready for indexing: {validation['reason']} "
                f"Missing: {', '.join(validation['missing'])}"
            )
            
            # Create queue item with 'invalid' status
            url = get_absolute_content_url(content_item)
            queue_item = GoogleIndexingQueue.objects.create(
                content_item=content_item,
                url=url,
                action=action,
                priority=priority,
                status='invalid',
                error_message=f"{validation['reason']}. Missing: {', '.join(validation['missing'])}"
            )
            
            return {
                'queued': False,
                'queue_item': queue_item,
                'validation': validation
            }
        
        # Content is ready, queue it
        url = get_absolute_content_url(content_item)
        
        # Check if already queued
        existing = GoogleIndexingQueue.objects.filter(
            content_item=content_item,
            status__in=['pending', 'processing']
        ).first()
        
        if existing:
            logger.debug(f"Content {content_item.id} already queued: {existing.id}")
            return {
                'queued': True,
                'queue_item': existing,
                'validation': validation,
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
        
        logger.info(f"✓ Queued for indexing: {content_item.get_title()} | Priority: {priority}")
        
        return {
            'queued': True,
            'queue_item': queue_item,
            'validation': validation
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
        
        Args:
            queue_item: GoogleIndexingQueue instance
        
        Returns:
            dict: {'success': bool, 'error': str, 'quota_exceeded': bool}
        """
        # Mark as processing
        queue_item.status = 'processing'
        queue_item.save(update_fields=['status', 'updated_at'])
        
        # Submit to Google
        result = notify_google_indexing_api(queue_item.url, queue_item.action)
        
        # Handle result
        if result['success']:
            # Success
            queue_item.mark_as_success(response=result.get('response'))
            GoogleIndexingQuota.increment_usage(success=True)
            
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
            # Max retries reached
            queue_item.mark_as_failed(
                error_message=f"Max retries reached. {error_message}",
                error_code=error_code,
                response=result.get('response')
            )
            GoogleIndexingQuota.increment_usage(success=False)
            
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
