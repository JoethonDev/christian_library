"""
Google Re-indexing Service
Handles bulk URL submission to Google Indexing API with rate limiting.
"""
import logging
import time
from typing import List, Dict, Tuple, Optional
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import transaction
from django.utils import timezone
from apps.media_manager.models import ContentItem
from apps.frontend_api.models import GoogleReindexingTask
from apps.frontend_api.google_seo_service import notify_google_indexing_api

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for Google API requests"""
    
    def __init__(self, rate_per_minute=200):
        """
        Initialize rate limiter.
        
        Args:
            rate_per_minute: Maximum requests per minute (default: 200 for Google)
        """
        self.rate_per_minute = rate_per_minute
        self.tokens = rate_per_minute
        self.last_update = time.time()
        self.lock_time = None
    
    def acquire(self, tokens=1):
        """
        Acquire tokens for requests. Blocks if rate limit would be exceeded.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            float: Time waited in seconds
        """
        now = time.time()
        time_passed = now - self.last_update
        
        # Refill tokens based on time passed
        self.tokens = min(
            self.rate_per_minute,
            self.tokens + (time_passed * self.rate_per_minute / 60.0)
        )
        self.last_update = now
        
        # If not enough tokens, wait
        if self.tokens < tokens:
            wait_time = ((tokens - self.tokens) * 60.0) / self.rate_per_minute
            logger.debug(f"Rate limiter: waiting {wait_time:.2f}s for {tokens} token(s)")
            time.sleep(wait_time)
            self.tokens = 0
            self.last_update = time.time()
            return wait_time
        
        self.tokens -= tokens
        return 0


class GoogleReindexingService:
    """Service for managing Google re-indexing operations"""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(rate_per_minute=200)
    
    def initiate_reindexing(
        self, 
        user, 
        content_type: Optional[str] = None, 
        include_sitemap: bool = True,
        force: bool = False
    ) -> str:
        """
        Initiate a new re-indexing task.
        
        Args:
            user: User initiating the task
            content_type: Type of content to re-index ('all', 'video', 'audio', 'pdf')
            include_sitemap: Whether to ping sitemap after completion
            force: If True, re-index ALL URLs even if already indexed
            
        Returns:
            str: Task UUID
        """
        from apps.frontend_api.models_indexing import GoogleIndexedUrl
        
        # Check for active tasks
        active_tasks = GoogleReindexingTask.objects.filter(
            status__in=['pending', 'in_progress']
        )
        if active_tasks.exists():
            raise ValueError("Another re-indexing operation is already in progress")
        
        # Get all URLs (including static pages)
        urls = self.get_active_urls(content_type, include_static=True)
        
        # Filter URLs based on force flag and registry
        urls_to_index = []
        
        if force:
            # Force: re-index ALL URLs
            urls_to_index = urls
            logger.info(f"Force re-index: queueing all {len(urls_to_index)} URLs")
        else:
            # Normal: only index not_indexed, failed, or needing re-index
            for url_info in urls:
                indexed_url = GoogleIndexedUrl.objects.filter(url=url_info['url']).first()
                
                if not indexed_url or indexed_url.status in ['not_indexed', 'failed'] or indexed_url.needs_reindex:
                    urls_to_index.append(url_info)
            
            logger.info(
                f"Normal re-index: queueing {len(urls_to_index)} URLs "
                f"(out of {len(urls)} total)"
            )
        
        # Create task
        task = GoogleReindexingTask.objects.create(
            status='pending',
            content_type=content_type or 'all',
            total_urls=len(urls_to_index),
            initiated_by=user,
            sitemap_included=include_sitemap
        )
        
        logger.info(
            f"Initiated re-indexing task {task.id} | "
            f"URLs: {len(urls_to_index)} | Force: {force}"
        )
        
        return str(task.id)
    
    def get_active_urls(self, content_type: Optional[str] = None, include_static: bool = True) -> List[Dict[str, str]]:
        """
        Get all active URLs for indexing including content and static pages.
        
        Args:
            content_type: Filter by content type ('video', 'audio', 'pdf') or None for all
            include_static: Whether to include static pages, tags, and feeds (default: True)
            
        Returns:
            List of dicts with URL metadata
        """
        from apps.frontend_api.services.url_generator_service import get_url_generator
        
        url_generator = get_url_generator()
        urls = url_generator.get_all_urls(content_type=content_type, include_static=include_static)
        
        logger.info(f"Collected {len(urls)} URLs for re-indexing")
        return urls
    
    def queue_urls_for_reindexing(
        self, 
        urls_batch: List[Dict[str, str]], 
        task_id: str,
        force: bool = False
    ) -> Tuple[int, int]:
        """
        Queue URLs for re-indexing via GoogleIndexingQueue.
        Replaces direct API submission with queue-based approach.
        
        Args:
            urls_batch: List of URL dictionaries with metadata
            task_id: UUID of the GoogleReindexingTask
            force: Force re-indexing even if already indexed
            
        Returns:
            Tuple of (queued_count, skipped_count)
        """
        from apps.frontend_api.services.google_indexing_queue_service import GoogleIndexingQueueService
        
        task = GoogleReindexingTask.objects.get(id=task_id)
        
        queued = 0
        skipped = 0
        
        for url_info in urls_batch:
            # Check for cancellation
            task.refresh_from_db()
            if task.status == 'cancelled':
                logger.info(f"Task {task_id} cancelled, stopping")
                break
            
            # Queue via service
            try:
                result = GoogleIndexingQueueService.queue_for_indexing(
                    content_item=None,  # Re-indexing works with URLs directly
                    url=url_info['url'],
                    url_type=url_info.get('url_type', 'content'),
                    action='URL_UPDATED',
                    priority=url_info.get('priority'),
                    force=force,
                    language=url_info.get('language', 'ar'),
                    **{k: v for k, v in url_info.items() if k not in ['url', 'content_item', 'url_type', 'priority', 'language', 'action']}
                )
                
                if result['queued']:
                    queued += 1
                else:
                    skipped += 1
            
            except Exception as e:
                logger.error(f"Error queueing URL {url_info['url']}: {e}")
                skipped += 1
            
            # Update task progress
            task.submitted_urls += 1
            task.save(update_fields=['submitted_urls', 'updated_at'])
        
        logger.info(f"Queued {queued} URLs for re-indexing, skipped {skipped}")
        
        return queued, skipped
    
    def submit_url_batch(
        self, 
        urls_batch: List[Dict[str, str]], 
        task_id: str
    ) -> Tuple[int, int, List[Dict]]:
        """
        Submit a batch of URLs to Google Indexing API.
        
        DEPRECATED: Use queue_urls_for_reindexing() instead.
        This method is kept for backward compatibility but will be removed in future versions.
        The queue-based approach provides better error handling and quota management.
        
        Args:
            urls_batch: List of URL dictionaries
            task_id: UUID of the GoogleReindexingTask
            
        Returns:
            Tuple of (successful_count, failed_count, errors)
        """
        logger.warning("submit_url_batch is deprecated. Use queue_urls_for_reindexing() instead.")
        
        task = GoogleReindexingTask.objects.get(id=task_id)
        
        successful = 0
        failed = 0
        errors = []
        
        for url_info in urls_batch:
            url = url_info['url']
            success = False  # Initialize to False
            
            # Check for cancellation
            task.refresh_from_db()
            if task.status == 'cancelled':
                logger.info(f"Task {task_id} cancelled, stopping batch submission")
                break
            
            # Acquire rate limit token
            wait_time = self.rate_limiter.acquire(1)
            
            # Submit to Google API
            try:
                result = notify_google_indexing_api(url, action='URL_UPDATED')
                success = result.get('success', False)
                
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append({
                        'url': url,
                        'type': 'api_failure',
                        'message': result.get('error', 'Google Indexing API returned failure'),
                        'error_code': result.get('error_code', 'UNKNOWN'),
                        'timestamp': timezone.now().isoformat()
                    })
            except Exception as e:
                failed += 1
                success = False
                error_msg = str(e)
                errors.append({
                    'url': url,
                    'type': 'exception',
                    'message': error_msg,
                    'timestamp': timezone.now().isoformat()
                })
                logger.error(f"Error submitting URL {url}: {e}")
            
            # Update task progress
            task.submitted_urls += 1
            task.successful_urls += (1 if success else 0)
            task.failed_urls += (0 if success else 1)
            task.save(update_fields=['submitted_urls', 'successful_urls', 'failed_urls', 'updated_at'])
        
        return successful, failed, errors
    
    def get_task_status(self, task_id: str) -> Dict:
        """
        Get current status of a re-indexing task.
        
        Args:
            task_id: UUID of the task
            
        Returns:
            Dict with task status information
        """
        try:
            task = GoogleReindexingTask.objects.get(id=task_id)
            
            return {
                'task_id': str(task.id),
                'status': task.status,
                'content_type': task.content_type,
                'progress': task.get_progress_percentage(),
                'total': task.total_urls,
                'submitted': task.submitted_urls,
                'successful': task.successful_urls,
                'failed': task.failed_urls,
                'estimated_remaining': task.get_estimated_time_remaining(),
                'error_summary': task.get_error_summary(),
                'success_rate': task.get_success_rate(),
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                'created_at': task.created_at.isoformat() if task.created_at else None,
            }
        except GoogleReindexingTask.DoesNotExist:
            return {'error': 'Task not found'}
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running re-indexing task.
        
        Args:
            task_id: UUID of the task
            
        Returns:
            bool: True if cancelled, False otherwise
        """
        try:
            task = GoogleReindexingTask.objects.get(id=task_id)
            
            if task.status in ['completed', 'failed', 'cancelled']:
                return False
            
            task.status = 'cancelled'
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            logger.info(f"Cancelled re-indexing task {task_id}")
            return True
        except GoogleReindexingTask.DoesNotExist:
            return False
    
    def get_reindexing_history(self, limit: int = 10):
        """
        Get recent re-indexing task history.
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            QuerySet of GoogleReindexingTask objects
        """
        return GoogleReindexingTask.objects.select_related('initiated_by').order_by('-created_at')[:limit]
    
    def estimate_duration(self, total_urls: int) -> int:
        """
        Estimate duration in seconds for re-indexing given number of URLs.
        
        Args:
            total_urls: Number of URLs to re-index
            
        Returns:
            int: Estimated duration in seconds
        """
        # With rate limit of 200 req/min, that's ~3.33 req/sec
        # Add some overhead for API latency
        avg_time_per_url = 0.4  # seconds (conservative estimate)
        return int(total_urls * avg_time_per_url)
