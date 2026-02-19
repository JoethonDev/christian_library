"""
API Upload Queue Management Service.
Handles queue operations, Redis locking, and rate limit management.
"""
import os
import logging
import hashlib
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.core.files.storage import default_storage
from django.db import transaction
from apps.media_manager.models import APIUploadQueue, ContentItem

logger = logging.getLogger(__name__)


class APIUploadQueueService:
    """
    Service for managing API upload queue operations.
    
    Features:
    - Type-based concurrency control (only one item per content type processing)
    - Redis-based locking for distributed systems
    - Automatic scheduling for rate-limited items
    - Queue position tracking
    - Admin actions (promote, cancel)
    """
    
    LOCK_TIMEOUT = 3600  # 1 hour lock timeout
    MAX_FILE_SIZE_MB = 2048  # 2GB max file size
    
    @classmethod
    def add_to_queue(cls, file, content_type, doc_file=None, metadata=None):
        """
        Add a file to the upload queue.
        
        Args:
            file: Uploaded file object
            content_type: Type of content (video/audio/pdf)
            doc_file: Optional document file for book content
            metadata: Optional metadata dict
        
        Returns:
            APIUploadQueue: Created queue item
        
        Raises:
            ValueError: If file is invalid or too large
        """
        # Validate file size
        file_size_mb = file.size / (1024 * 1024)
        if file_size_mb > cls.MAX_FILE_SIZE_MB:
            raise ValueError(f'File size {file_size_mb:.2f}MB exceeds maximum of {cls.MAX_FILE_SIZE_MB}MB')
        
        # Validate content type
        if content_type not in ['video', 'audio', 'pdf']:
            raise ValueError(f'Invalid content type: {content_type}')
        
        # Save file to temporary storage
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'api_uploads', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        file_path = os.path.join(temp_dir, f'{timezone.now().timestamp()}_{file.name}')
        
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        # Save doc file if provided
        doc_file_path = None
        if doc_file:
            doc_file_path = os.path.join(temp_dir, f'{timezone.now().timestamp()}_doc_{doc_file.name}')
            with open(doc_file_path, 'wb+') as destination:
                for chunk in doc_file.chunks():
                    destination.write(chunk)
        
        # Create queue item
        queue_item = APIUploadQueue.objects.create(
            file_name=file.name,
            file_path=file_path,
            doc_file_path=doc_file_path,
            content_type=content_type,
            file_size_mb=file_size_mb,
            metadata=metadata or {},
            status='pending',
            queue_status='waiting'
        )
        
        logger.info(f'Added {file.name} to queue (ID: {queue_item.id}, Type: {content_type})')
        
        # Check if can process immediately
        if cls.can_process_type(content_type):
            queue_item.queue_status = 'ready'
            queue_item.status = 'queued'
            queue_item.save(update_fields=['queue_status', 'status', 'updated_at'])
            
            # Trigger processing task
            from apps.media_manager.tasks import process_upload_queue_item
            process_upload_queue_item.delay(str(queue_item.id))
        
        return queue_item
    
    @classmethod
    def can_process_type(cls, content_type):
        """
        Check if a content type can be processed (no concurrent processing).
        Uses Redis lock for distributed concurrency control.
        
        Args:
            content_type: Type of content (video/audio/pdf)
        
        Returns:
            bool: True if can process, False if another item is processing
        """
        lock_key = f'api_upload_lock:{content_type}'
        
        try:
            # Check if lock exists
            lock_exists = cache.get(lock_key)
            return lock_exists is None
        except Exception as e:
            logger.error(f'Error checking process lock: {e}')
            # On error, allow processing (fail open)
            return True
    
    @classmethod
    def acquire_processing_lock(cls, content_type, queue_item_id):
        """
        Acquire processing lock for a content type.
        
        Args:
            content_type: Type of content
            queue_item_id: ID of queue item acquiring lock
        
        Returns:
            bool: True if lock acquired, False otherwise
        """
        lock_key = f'api_upload_lock:{content_type}'
        
        try:
            # Try to set lock (NX = only if not exists)
            acquired = cache.set(lock_key, str(queue_item_id), timeout=cls.LOCK_TIMEOUT, nx=True)
            if acquired:
                logger.info(f'Acquired processing lock for {content_type} (item: {queue_item_id})')
            else:
                logger.warning(f'Failed to acquire lock for {content_type} (item: {queue_item_id})')
            return acquired
        except Exception as e:
            logger.error(f'Error acquiring lock: {e}')
            return False
    
    @classmethod
    def release_processing_lock(cls, content_type):
        """
        Release processing lock for a content type.
        
        Args:
            content_type: Type of content
        """
        lock_key = f'api_upload_lock:{content_type}'
        
        try:
            cache.delete(lock_key)
            logger.info(f'Released processing lock for {content_type}')
        except Exception as e:
            logger.error(f'Error releasing lock: {e}')
    
    @classmethod
    def get_next_ready_item(cls, content_type):
        """
        Get the next queue item ready for processing.
        
        Args:
            content_type: Type of content
        
        Returns:
            APIUploadQueue or None: Next item to process
        """
        now = timezone.now()
        
        # Find items that are ready to process
        return APIUploadQueue.objects.filter(
            content_type=content_type,
            status__in=['pending', 'queued', 'rate_limited']
        ).filter(
            # Must be scheduled for now or past, or not scheduled at all
            models.Q(scheduled_for__lte=now) | models.Q(scheduled_for__isnull=True)
        ).filter(
            # Not exceeded delay limit
            delay_count__lt=7
        ).order_by('-priority', 'created_at').first()
    
    @classmethod
    def handle_rate_limit_exceeded(cls, queue_item):
        """
        Handle Gemini rate limit exceeded for a queue item.
        Schedules for next day at 3:00 AM.
        
        Args:
            queue_item: APIUploadQueue instance
        """
        logger.warning(f'Rate limit exceeded for queue item {queue_item.id}')
        queue_item.schedule_for_next_day()
        
        # Release lock so other types can process
        cls.release_processing_lock(queue_item.content_type)
        
        # Check if there's another item of different type that can process
        cls._trigger_next_in_queue()
    
    @classmethod
    def _trigger_next_in_queue(cls):
        """Trigger processing for next available queue item."""
        for content_type in ['video', 'audio', 'pdf']:
            if cls.can_process_type(content_type):
                next_item = cls.get_next_ready_item(content_type)
                if next_item:
                    next_item.queue_status = 'ready'
                    next_item.save(update_fields=['queue_status', 'updated_at'])
                    
                    from apps.media_manager.tasks import process_upload_queue_item
                    process_upload_queue_item.delay(str(next_item.id))
                    break
    
    @classmethod
    def process_queue_item(cls, queue_item_id):
        """
        Process a queue item by creating ContentItem and triggering pipeline.
        
        Args:
            queue_item_id: UUID of queue item
        
        Returns:
            ContentItem or None: Created content item if successful
        """
        try:
            queue_item = APIUploadQueue.objects.get(id=queue_item_id)
        except APIUploadQueue.DoesNotExist:
            logger.error(f'Queue item {queue_item_id} not found')
            return None
        
        # Acquire lock
        if not cls.acquire_processing_lock(queue_item.content_type, queue_item_id):
            logger.warning(f'Could not acquire lock for {queue_item.id}')
            return None
        
        try:
            # Update status
            queue_item.status = 'processing'
            queue_item.processing_started_at = timezone.now()
            queue_item.save(update_fields=['status', 'processing_started_at', 'updated_at'])
            
            # Create ContentItem using upload service
            from apps.media_manager.services.upload_service import UploadService
            
            with open(queue_item.file_path, 'rb') as f:
                # Get metadata from queue item
                metadata = queue_item.metadata or {}
                
                # Create appropriate service based on content type
                if queue_item.content_type == 'video':
                    from django.core.files.uploadedfile import InMemoryUploadedFile
                    file_obj = InMemoryUploadedFile(
                        f, None, queue_item.file_name, 
                        'video/mp4', os.path.getsize(queue_item.file_path), None
                    )
                    content_item = UploadService.handle_video_upload(
                        file_obj,
                        metadata.get('title_ar', ''),
                        metadata.get('title_en', ''),
                        metadata.get('description_ar', ''),
                        metadata.get('description_en', ''),
                        metadata.get('tags', [])
                    )
                elif queue_item.content_type == 'audio':
                    from django.core.files.uploadedfile import InMemoryUploadedFile
                    file_obj = InMemoryUploadedFile(
                        f, None, queue_item.file_name,
                        'audio/mpeg', os.path.getsize(queue_item.file_path), None
                    )
                    content_item = UploadService.handle_audio_upload(
                        file_obj,
                        metadata.get('title_ar', ''),
                        metadata.get('title_en', ''),
                        metadata.get('description_ar', ''),
                        metadata.get('description_en', ''),
                        metadata.get('tags', [])
                    )
                else:  # pdf
                    from django.core.files.uploadedfile import InMemoryUploadedFile
                    file_obj = InMemoryUploadedFile(
                        f, None, queue_item.file_name,
                        'application/pdf', os.path.getsize(queue_item.file_path), None
                    )
                    content_item = UploadService.handle_pdf_upload(
                        file_obj,
                        metadata.get('title_ar', ''),
                        metadata.get('title_en', ''),
                        metadata.get('description_ar', ''),
                        metadata.get('description_en', ''),
                        metadata.get('tags', [])
                    )
            
            # Update queue item
            queue_item.content_item = content_item
            queue_item.status = 'completed'
            queue_item.completed_at = timezone.now()
            queue_item.save(update_fields=['content_item', 'status', 'completed_at', 'updated_at'])
            
            # Clean up temp files
            cls._cleanup_temp_files(queue_item)
            
            logger.info(f'Successfully processed queue item {queue_item.id}')
            
            return content_item
            
        except Exception as e:
            logger.error(f'Error processing queue item {queue_item.id}: {e}', exc_info=True)
            queue_item.status = 'failed'
            queue_item.error_message = str(e)
            queue_item.gemini_attempts += 1
            queue_item.save(update_fields=['status', 'error_message', 'gemini_attempts', 'updated_at'])
            return None
        finally:
            # Always release lock
            cls.release_processing_lock(queue_item.content_type)
            
            # Trigger next item in queue
            cls._trigger_next_in_queue()
    
    @classmethod
    def _cleanup_temp_files(cls, queue_item):
        """Clean up temporary files for a queue item."""
        try:
            if os.path.exists(queue_item.file_path):
                os.remove(queue_item.file_path)
            if queue_item.doc_file_path and os.path.exists(queue_item.doc_file_path):
                os.remove(queue_item.doc_file_path)
        except Exception as e:
            logger.error(f'Error cleaning up temp files: {e}')
    
    @classmethod
    def promote_item(cls, queue_item_id):
        """
        Admin action to promote a queue item to process immediately.
        
        Args:
            queue_item_id: UUID of queue item
        """
        try:
            queue_item = APIUploadQueue.objects.get(id=queue_item_id)
            queue_item.promote_to_ready()
            
            # Trigger processing if can acquire lock
            if cls.can_process_type(queue_item.content_type):
                from apps.media_manager.tasks import process_upload_queue_item
                process_upload_queue_item.delay(str(queue_item.id))
            
            logger.info(f'Promoted queue item {queue_item.id}')
        except APIUploadQueue.DoesNotExist:
            logger.error(f'Queue item {queue_item_id} not found')
    
    @classmethod
    def cancel_item(cls, queue_item_id):
        """
        Admin action to cancel a queue item.
        
        Args:
            queue_item_id: UUID of queue item
        """
        try:
            queue_item = APIUploadQueue.objects.get(id=queue_item_id)
            queue_item.status = 'cancelled'
            queue_item.save(update_fields=['status', 'updated_at'])
            
            # Clean up temp files
            cls._cleanup_temp_files(queue_item)
            
            logger.info(f'Cancelled queue item {queue_item.id}')
        except APIUploadQueue.DoesNotExist:
            logger.error(f'Queue item {queue_item_id} not found')
    
    @classmethod
    def get_queue_dashboard_data(cls):
        """
        Get dashboard data for admin interface.
        
        Returns:
            dict: Dashboard statistics and queue items
        """
        from django.db.models import Count, Q
        
        # Statistics by status
        status_stats = APIUploadQueue.objects.values('status').annotate(count=Count('id'))
        
        # Items by content type
        type_stats = APIUploadQueue.objects.filter(
            status__in=['pending', 'queued', 'processing']
        ).values('content_type').annotate(count=Count('id'))
        
        # Currently processing items
        processing_items = APIUploadQueue.objects.filter(
            status='processing'
        ).select_related('content_item')
        
        # Delayed items
        delayed_items = APIUploadQueue.objects.filter(
            status='rate_limited',
            queue_status='delayed'
        ).order_by('scheduled_for')
        
        return {
            'status_stats': {item['status']: item['count'] for item in status_stats},
            'type_stats': {item['content_type']: item['count'] for item in type_stats},
            'processing_items': list(processing_items),
            'delayed_items': list(delayed_items),
            'total_in_queue': APIUploadQueue.objects.filter(
                status__in=['pending', 'queued', 'rate_limited']
            ).count(),
        }


# Import for using Q in get_next_ready_item
from django.db import models
