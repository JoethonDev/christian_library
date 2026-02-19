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
        include_sitemap: bool = True
    ) -> str:
        """
        Initiate a new re-indexing task.
        
        Args:
            user: User initiating the task
            content_type: Type of content to re-index ('all', 'video', 'audio', 'pdf')
            include_sitemap: Whether to ping sitemap after completion
            
        Returns:
            str: Task UUID
        """
        # Check for active tasks
        active_tasks = GoogleReindexingTask.objects.filter(
            status__in=['pending', 'in_progress']
        )
        if active_tasks.exists():
            raise ValueError("Another re-indexing operation is already in progress")
        
        # Get URL count
        urls = self.get_active_urls(content_type)
        
        # Create task
        task = GoogleReindexingTask.objects.create(
            status='pending',
            content_type=content_type or 'all',
            total_urls=len(urls),
            initiated_by=user,
            sitemap_included=include_sitemap
        )
        
        logger.info(f"Initiated re-indexing task {task.id} for {len(urls)} URLs")
        
        return str(task.id)
    
    def get_active_urls(self, content_type: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get all active content URLs with language variants.
        
        Args:
            content_type: Filter by content type ('video', 'audio', 'pdf') or None for all
            
        Returns:
            List of dicts with 'url' and 'content_type' keys
        """
        # Base queryset - only active content
        queryset = ContentItem.objects.filter(is_active=True)
        
        # Filter by content type if specified
        if content_type and content_type != 'all':
            queryset = queryset.filter(content_type=content_type)
        
        # Get site domain
        try:
            current_site = Site.objects.get_current()
            domain = current_site.domain
            protocol = 'https'
        except Exception as e:
            logger.error(f"Could not get site domain: {e}")
            return []
        
        urls = []
        
        # Get all content items
        for item in queryset.select_related('user').iterator(chunk_size=500):
            # Add URL for each language variant (ar and en)
            for lang in ['ar', 'en']:
                try:
                    url_path = item.get_absolute_url()
                    # Replace language prefix
                    if url_path.startswith('/ar/') or url_path.startswith('/en/'):
                        url_path = f'/{lang}{url_path[3:]}'
                    else:
                        url_path = f'/{lang}{url_path}'
                    
                    absolute_url = f"{protocol}://{domain}{url_path}"
                    
                    urls.append({
                        'url': absolute_url,
                        'content_type': item.content_type,
                        'content_id': str(item.id),
                        'language': lang
                    })
                except Exception as e:
                    logger.warning(f"Could not build URL for content {item.id}: {e}")
                    continue
        
        logger.info(f"Collected {len(urls)} URLs for re-indexing")
        return urls
    
    def submit_url_batch(
        self, 
        urls_batch: List[Dict[str, str]], 
        task_id: str
    ) -> Tuple[int, int, List[Dict]]:
        """
        Submit a batch of URLs to Google Indexing API.
        
        Args:
            urls_batch: List of URL dictionaries
            task_id: UUID of the GoogleReindexingTask
            
        Returns:
            Tuple of (successful_count, failed_count, errors)
        """
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
                success = notify_google_indexing_api(url, action='URL_UPDATED')
                
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append({
                        'url': url,
                        'type': 'api_failure',
                        'message': 'Google Indexing API returned failure',
                        'timestamp': timezone.now().isoformat()
                    })
            except Exception as e:
                failed += 1
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
