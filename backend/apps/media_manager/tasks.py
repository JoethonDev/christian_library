import os
from celery import shared_task
from django.apps import apps
from django.conf import settings
from apps.core.task_monitor import TaskMonitor
import logging
from core.tasks.media_processing import upload_video_to_r2, upload_audio_to_r2, upload_pdf_to_r2

def get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_and_index_contentitem(self, contentitem_id, user_id=None):
    """
    Extract text from PDF and update search index.
    Retries up to 3 times with 60 second delays on failure.
    Now includes task monitoring for admin dashboard.
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    # Register task for monitoring with checklist tracking
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='PDF Text Extraction',
        user_id=user_id,
        metadata={'content_id': contentitem_id, 'content_type': 'pdf'},
        checklist_steps=['text_extraction', 'search_indexing', 'finalization']
    )
    
    try:
        logger.info(f"Starting extraction and indexing for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Only process PDFs
        if item.content_type != 'pdf':
            logger.warning(f"ContentItem {contentitem_id} is not a PDF, skipping extraction")
            TaskMonitor.update_task_status(
                self.request.id, 
                'SUCCESS', 
                {'message': 'Skipped - not a PDF'}
            )
            return
        
        # Update task status to indicate processing has started (only if not already completed)
        # For PDFs, the file processing (optimization) completes first, then text extraction happens
        # We don't want to overwrite 'completed' status from file processing
        if item.processing_status != 'completed':
            item.processing_status = 'processing'
            item.save(update_fields=['processing_status'])
        else:
            logger.debug(f"ContentItem {contentitem_id} already has processing_status='completed', skipping update")
        
        TaskMonitor.update_progress(
            self.request.id, 
            message='Transcribing sacred text content for search capabilities...', 
            step='text_extraction'
        )
        
        # Extract text from PDF (includes OCR fallback)
        item.extract_text_from_pdf()
        
        # Save the extracted content first
        item.save(update_fields=["book_content"])
        
        # Mark text extraction as completed
        TaskMonitor.update_checklist_step(
            self.request.id,
            'text_extraction',
            completed=True,
            message='Text extraction completed successfully'
        )
        
        TaskMonitor.update_progress(
            self.request.id, 
            message='Updating internal library search engines...', 
            step='search_indexing'
        )
        
        # Update search vector using UPDATE query to properly evaluate SearchVector expression
        if item.book_content:
            from django.contrib.postgres.search import SearchVector
            
            ContentItem.objects.filter(id=item.id).update(
                search_vector=(
                    SearchVector('title_ar', weight='A', config='arabic') +
                    SearchVector('description_ar', weight='B', config='arabic') +
                    SearchVector('book_content', weight='C', config='arabic')
                )
            )
        else:
            # Clear search vector if no content
            ContentItem.objects.filter(id=item.id).update(search_vector=None)
        
        # Mark search indexing as completed
        TaskMonitor.update_checklist_step(
            self.request.id,
            'search_indexing', 
            completed=True,
            message='Search indexing completed successfully'
        )
        
        extracted_length = len(item.book_content) if item.book_content else 0
        logger.info(f"Successfully completed extraction and indexing for ContentItem {contentitem_id}: {extracted_length} characters")
        
        # Parallel Trigger: Trigger SEO generation and R2 upload at the same time
        if item.content_type in ['video', 'audio', 'pdf']:
            TaskMonitor.update_progress(
                self.request.id, 
                message="Starting AI enrichment and cloud delivery...", 
                step="finalization"
            )
            
            # 1. Trigger SEO generation
            generate_seo_metadata_task.delay(str(item.id))
            
            # 2. Trigger R2 upload
            if getattr(settings, 'R2_ENABLED', False):
                meta = item.get_meta_object()
                if meta:
                    if item.content_type == 'video':
                        upload_video_to_r2.delay(str(meta.id))
                    elif item.content_type == 'audio':
                        upload_audio_to_r2.delay(str(meta.id))
                    elif item.content_type == 'pdf':
                        upload_pdf_to_r2.delay(str(meta.id))
                    logger.info(f"Triggered parallel R2 upload for {item.content_type}: {meta.id}")
        
        # Mark finalization as completed
        TaskMonitor.update_checklist_step(
            self.request.id,
            'finalization',
            completed=True,
            message='Parallel tasks triggered successfully'
        )
        
        # Mark task as successful
        TaskMonitor.update_task_status(
            self.request.id, 
            'SUCCESS', 
            {
                'message': 'Sacred text successfully indexed for search',
                'extracted_chars': extracted_length
            }
        )
        
    except ContentItem.DoesNotExist:
        error_msg = f"ContentItem {contentitem_id} not found"
        logger.error(error_msg)
        TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=error_msg)
        # Don't retry for non-existent items
        return
        
    except Exception as exc:
        error_msg = f"Error processing ContentItem {contentitem_id}: {str(exc)}"
        logger.error(error_msg, exc_info=True)
        
        TaskMonitor.update_task_status(
            self.request.id, 
            'RETRY', 
            {'message': f'Retry {self.request.retries + 1}/3', 'error': str(exc)}
        )
        
        # Retry the task with exponential backoff
        try:
            self.retry(countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for ContentItem {contentitem_id}")
            try:
                item = ContentItem.objects.get(id=contentitem_id)
                item.processing_status = 'failed'
                item.save(update_fields=['processing_status'])
            except:
                pass


@shared_task(bind=True, max_retries=10, default_retry_delay=600)
def generate_seo_metadata_task(self, contentitem_id, force_regenerate=False):
    """
    Generate SEO metadata for content using Gemini AI with enhanced retry logic.
    
    Features:
    - Isolated to dedicated 'seo' worker queue
    - Enhanced Gemini rate limit detection and handling
    - Server Errors (5xx): Retry after 10 minutes, max 3 times for these specifically.
    - All Errors: If 3 total attempts fail, schedule for next day at 3:00 AM.
    - Up to 10 total retries allowed by Celery to accommodate multi-day delays.
    
    Args:
        contentitem_id: ID of the ContentItem to generate SEO for
        force_regenerate: If True, regenerate even if SEO data already exists
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    # Register task for monitoring with checklist tracking
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='AI SEO Metadata Generation',
        metadata={
            'content_id': contentitem_id, 
            'attempt': self.request.retries + 1, 
            'force': force_regenerate,
            'max_retries': self.max_retries,
            'queue': 'gemini'
        },
        checklist_steps=['validation', 'ai_generation', 'content_update']
    )
    
    try:
        logger.info(f"🔄 Starting SEO metadata generation for ContentItem {contentitem_id} (attempt {self.request.retries + 1}/{self.max_retries + 1}, force={force_regenerate})")
        
        TaskMonitor.update_progress(
            self.request.id, 
            message='Validating content item...', 
            step='validation'
        )
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Skip if SEO metadata already exists (unless force_regenerate is True)
        if not force_regenerate and item.has_seo_metadata():
            logger.info(f"ContentItem {contentitem_id} already has SEO metadata. Skipping generation (use force_regenerate=True to override).")
            item.seo_processing_status = 'completed'
            item.save(update_fields=['seo_processing_status'])
            
            # Mark all checklist steps as completed for skip scenario
            TaskMonitor.update_checklist_step(self.request.id, 'validation', True, "Content already has SEO metadata")
            TaskMonitor.update_checklist_step(self.request.id, 'ai_generation', True, "Skipped - already exists") 
            TaskMonitor.update_checklist_step(self.request.id, 'content_update', True, "No update needed")
            
            TaskMonitor.update_task_status(
                self.request.id, 
                'SUCCESS', 
                {'message': 'SEO metadata already exists - skipped'}
            )
            return
        
        # Mark validation as completed
        TaskMonitor.update_checklist_step(
            self.request.id,
            'validation', 
            True,
            "Content validation successful"
        )
        
        # Update SEO status to processing
        item.seo_processing_status = 'processing'
        item.save(update_fields=['seo_processing_status'])
        
        TaskMonitor.update_progress(
            self.request.id, 
            message='Preparing content for AI analysis...', 
            step='ai_generation'
        )
        
        # Get the media file path
        meta = item.get_meta_object()
        if not meta or not hasattr(meta, 'original_file') or not meta.original_file:
            logger.warning(f"No media file found for ContentItem {contentitem_id}")
            item.seo_processing_status = 'failed'
            item.save(update_fields=['seo_processing_status'])
            TaskMonitor.update_task_status(
                self.request.id, 
                'FAILURE', 
                {'message': 'No media file found', 'progress': 100}
            )
            return
        
        file_path = meta.original_file.path
        if not os.path.exists(file_path):
             logger.warning(f"Media file not found at {file_path}")
             item.seo_processing_status = 'failed'
             item.save(update_fields=['seo_processing_status'])
             TaskMonitor.update_task_status(
                 self.request.id, 
                 'FAILURE', 
                 {'message': 'Media file not found on disk', 'progress': 100}
             )
             return

        # Import Gemini service
        from apps.media_manager.services.gemini_service import get_gemini_service
        
        TaskMonitor.update_progress(
            self.request.id, 
            30,
            'Connecting to AI service...', 
            'AI Service'
        )
        
        # Generate SEO metadata
        service = get_gemini_service()
        if not service.is_available():
            logger.error("Gemini AI service not available")
            raise Exception("Gemini AI service not available")
        
        TaskMonitor.update_progress(
            self.request.id, 
            50,
            f'Generating SEO metadata with AI (attempt {self.request.retries + 1}/3)...', 
            'AI Processing'
        )
        
        success, seo_metadata = service.generate_seo_metadata(file_path, item.content_type)
        
        if success and seo_metadata:
            TaskMonitor.update_progress(
                self.request.id, 
                80,
                'Updating content with AI-generated metadata...', 
                'Saving'
            )
            
            # Update the content item with SEO metadata
            success_update = item.update_seo_from_gemini(seo_metadata)
            
            if success_update:
                # Mark SEO processing as completed
                item.seo_processing_status = 'completed'
                
                # Only update processing_status if not already completed
                # (The file processing task should have already marked it as completed)
                update_fields = ['seo_processing_status']
                if item.processing_status != 'completed':
                    item.processing_status = 'completed'
                    update_fields.append('processing_status')
                
                item.save(update_fields=update_fields)
                
                logger.info(f"Successfully generated and updated SEO metadata for ContentItem {contentitem_id}")
                
                TaskMonitor.update_task_status(
                    self.request.id, 
                    'SUCCESS', 
                    {'message': 'AI SEO metadata generated successfully', 'progress': 100}
                )
                
                # Check for cleanup
                finalize_media_processing.delay(str(item.id))
            else:
                logger.error(f"Failed to update SEO metadata for ContentItem {contentitem_id}")
                item.seo_processing_status = 'failed'
                item.save(update_fields=['seo_processing_status'])
                TaskMonitor.update_task_status(
                    self.request.id, 
                    'FAILURE', 
                    {'message': 'Failed to save AI-generated metadata', 'progress': 100}
                )
        else:
            error_msg = seo_metadata.get('error', 'Unknown error') if isinstance(seo_metadata, dict) else 'Generation failed'
            logger.error(f"Failed to generate SEO metadata for ContentItem {contentitem_id}: {error_msg}")
            raise Exception(f"SEO generation failed: {error_msg}")
        
    except ContentItem.DoesNotExist:
        logger.error(f"ContentItem {contentitem_id} not found")
        TaskMonitor.update_task_status(
            self.request.id, 
            'FAILURE', 
            {'message': 'Content not found', 'progress': 100}
        )
        return
        
    except Exception as exc:
        logger.error(f"💥 Error generating SEO metadata for ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        
        # Enhanced error detection
        is_rate_limit_error = _is_gemini_rate_limit_error(exc)
        is_server_error = _is_gemini_server_error(exc)
        
        # Plan logic: 
        # 1. Any error after 3 failed attempts (retries 0, 1, 2) -> schedule for next day 3 AM
        # 2. Server errors (5xx) -> retry after 10 mins (600s)
        # 3. Other errors -> retry with current default or rate limit logic
        
        if self.request.retries >= 2:  # 0, 1, 2 attempts failed, now on 3rd retry or finishing it
            # This was the 3rd attempt (retries = 2)
            next_3am_delay = _calculate_next_3am_delay()
            logger.warning(f"❌ 3 attempts failed for ContentItem {contentitem_id}. Scheduling next attempt for 3:00 AM.")
            
            TaskMonitor.update_task_status(
                self.request.id, 
                'RETRY',
                {
                    'message': f'3 attempts failed - rescheduling for 3:00 AM (Error: {str(exc)[:100]})',
                    'retry_at': '3:00 AM',
                    'delay_hours': round(next_3am_delay/3600, 1)
                }
            )
            
            # Retry at 3:00 AM tomorrow
            raise self.retry(exc=exc, countdown=next_3am_delay)
            
        if is_server_error:
            logger.warning(f"🔌 Gemini server error detected (5xx) for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            countdown = 600  # 10 minutes
            
            TaskMonitor.update_task_status(
                self.request.id, 
                'RETRY',
                {
                    'message': f'Server error (5xx) - retrying in 10 minutes (attempt {self.request.retries + 1}/3)',
                    'countdown': countdown,
                    'error_type': 'server'
                }
            )
            
            raise self.retry(exc=exc, countdown=countdown)
            
        if is_rate_limit_error:
            logger.warning(f"🚦 Gemini rate limit detected for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            # For rate limits, we'll use a shorter retry or just wait for the next 3AM if we prefer,
            # but the requirement says for ANY error 3 attempts fail then 3 AM.
            # So if it's attempt 1 or 2, we can retry sooner.
            countdown = 300 # 5 minutes for rate limit before 3rd attempt
            
            TaskMonitor.update_task_status(
                self.request.id, 
                'RETRY',
                {
                    'message': f'Rate limited - retrying in 5 minutes (attempt {self.request.retries + 1}/3)',
                    'rate_limited': True,
                    'countdown': countdown
                }
            )
            
            raise self.retry(exc=exc, countdown=countdown)
        
        # Standard fallback for other errors
        countdown = 120 * (2 ** self.request.retries)
        logger.info(f"🔄 Standard retry for ContentItem {contentitem_id} in {countdown}s (attempt {self.request.retries + 1})")
        
        TaskMonitor.update_task_status(
            self.request.id, 
            'RETRY',
            {
                'message': f'Error retry in {countdown}s (attempt {self.request.retries + 1}/3)',
                'countdown': countdown,
                'error_type': 'standard'
            }
        )
        
        raise self.retry(exc=exc, countdown=countdown)

def _is_gemini_rate_limit_error(exception):
    """Detect if the exception is a Gemini API rate limit error"""
    error_str = str(exception).lower()
    rate_limit_indicators = [
        'rate limit',
        'quota exceeded', 
        'too many requests',
        'resource exhausted',
        '429',
        'credits exhausted',
        'quota_exceeded',
        'rate_limit_exceeded'
    ]
    return any(indicator in error_str for indicator in rate_limit_indicators)

def _is_gemini_server_error(exception):
    """Detect if the exception is a Gemini API server error (5xx)"""
    error_str = str(exception).lower()
    server_error_indicators = [
        '500', '502', '503', '504',
        'internal server error',
        'service unavailable',
        'gateway timeout',
        'bad gateway',
        'upstream error'
    ]
    return any(indicator in error_str for indicator in server_error_indicators)

def _calculate_next_3am_delay():
    """Calculate seconds until next 3:00 AM"""
    from django.utils import timezone
    from datetime import time, timedelta
    
    now = timezone.now()
    
    # Create 3:00 AM today
    today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
    
    # If it's already past 3:00 AM today, schedule for tomorrow
    if now >= today_3am:
        tomorrow_3am = today_3am + timedelta(days=1)
        target_time = tomorrow_3am
    else:
        target_time = today_3am
    
    delay_seconds = (target_time - now).total_seconds()
    
    # Minimum delay of 1 hour to avoid immediate retries
    return max(delay_seconds, 3600)


@shared_task
def finalize_media_processing(contentitem_id):
    """
    Check if both R2 upload and SEO generation are finished.
    If both are done, safe to delete local files.
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    from core.tasks.media_processing import delete_files_task
    from pathlib import Path
    import os
    
    try:
        item = ContentItem.objects.get(id=contentitem_id)
        meta = item.get_meta_object()
        
        if not meta:
            return
            
        # Conditions for cleanup:
        # 1. R2 upload is completed (or not enabled)
        r2_done = not getattr(settings, 'R2_ENABLED', False) or meta.r2_upload_status == 'completed'
        
        # 2. SEO generation is completed or failed (don't hang forever if AI fails)
        seo_done = item.seo_processing_status in ['completed', 'failed']
        
        if r2_done and seo_done:
            logger.info(f"Both R2 and SEO finished for {contentitem_id}. Cleaning up local files.")
            
            local_paths = []
            try:
                # 1. Original file
                if meta.original_file and os.path.exists(meta.original_file.path):
                    local_paths.append(str(meta.original_file.path))
                
                # 2. Content type specific processed files
                if item.content_type == 'video':
                    hls_dir = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / str(item.id)
                    if hls_dir.exists():
                        local_paths.append(str(hls_dir))
                elif item.content_type == 'audio':
                    if hasattr(meta, 'compressed_file') and meta.compressed_file and os.path.exists(meta.compressed_file.path):
                        local_paths.append(str(meta.compressed_file.path))
                elif item.content_type == 'pdf':
                    if hasattr(meta, 'optimized_file') and meta.optimized_file and os.path.exists(meta.optimized_file.path):
                        local_paths.append(str(meta.optimized_file.path))
                
                if local_paths and item.has_seo_metadata():
                    delete_files_task.delay(local_paths)
                    logger.info(f"Queued deletion for {len(local_paths)} paths for item {item.id}")
                    
            except Exception as e:
                logger.warning(f"Error preparing local files for deletion for item {item.id}: {e}")
        else:
            logger.info(f"Finalize deferred for {contentitem_id}: R2={r2_done}, SEO={seo_done}")
            
    except ContentItem.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error in finalize_media_processing: {str(e)}")


@shared_task
def bulk_generate_seo_metadata(content_type=None, limit=None):
    """
    Generate SEO metadata for content items that don't have it yet.
    
    Args:
        content_type: Optional filter by content type ('video', 'audio', 'pdf')
        limit: Optional limit on number of items to process
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    try:
        # Build queryset for items without SEO metadata
        queryset = ContentItem.objects.filter(
            is_active=True,
            seo_keywords_ar__len=0,  # No Arabic keywords yet
            seo_keywords_en__len=0   # No English keywords yet
        )
        
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        
        if limit:
            queryset = queryset[:limit]
        
        count = 0
        for item in queryset:
            try:
                # Check if media file exists
                meta = item.get_meta_object()
                if meta and hasattr(meta, 'original_file') and meta.original_file:
                    generate_seo_metadata_task.delay(str(item.id))
                    count += 1
                else:
                    logger.warning(f"No media file for ContentItem {item.id}, skipping SEO generation")
            except Exception as e:
                logger.error(f"Error queuing SEO generation for ContentItem {item.id}: {str(e)}")
        
        logger.info(f"Queued SEO metadata generation for {count} content items")
        return count
        
    except Exception as exc:
        logger.error(f"Error in bulk SEO metadata generation: {str(exc)}", exc_info=True)
        return 0


@shared_task
def aggregate_daily_content_views():
    """
    Aggregate ContentViewEvent records into DailyContentViewSummary.
    Should be run nightly via Celery Beat to maintain performance.
    Processes events from yesterday and updates summary records.
    Counts both total views and unique views (by IP address).
    """
    from django.db.models import Count
    from django.utils import timezone
    from datetime import datetime, timedelta
    from apps.media_manager.models import ContentViewEvent, DailyContentViewSummary
    
    logger = logging.getLogger(__name__)
    
    try:
        # Process events from yesterday
        yesterday = timezone.now().date() - timedelta(days=1)
        start_datetime = datetime.combine(yesterday, datetime.min.time())
        end_datetime = datetime.combine(yesterday, datetime.max.time())
        
        # Make datetimes timezone-aware
        start_datetime = timezone.make_aware(start_datetime)
        end_datetime = timezone.make_aware(end_datetime)
        
        logger.info(f"Aggregating view events for {yesterday}")
        
        # Get events from yesterday grouped by content_type and content_id
        events = ContentViewEvent.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        ).values('content_type', 'content_id').annotate(
            count=Count('id')
        )
        
        aggregated_count = 0
        for event_data in events:
            # Count total views
            total_views = event_data['count']
            
            # Count unique views (distinct IP addresses)
            unique_views = ContentViewEvent.objects.filter(
                timestamp__gte=start_datetime,
                timestamp__lte=end_datetime,
                content_type=event_data['content_type'],
                content_id=event_data['content_id']
            ).values('ip_address').distinct().count()
            
            # Update or create summary record
            summary, created = DailyContentViewSummary.objects.update_or_create(
                content_type=event_data['content_type'],
                content_id=event_data['content_id'],
                date=yesterday,
                defaults={
                    'view_count': total_views,
                    'unique_view_count': unique_views
                }
            )
            aggregated_count += 1
            
            if created:
                logger.debug(f"Created summary: {event_data['content_type']} - {event_data['content_id']} on {yesterday}: {total_views} views ({unique_views} unique)")
            else:
                logger.debug(f"Updated summary: {event_data['content_type']} - {event_data['content_id']} on {yesterday}: {total_views} views ({unique_views} unique)")
        
        logger.info(f"Successfully aggregated {aggregated_count} content view summaries for {yesterday}")
        
        # Optional: Clean up old events (older than 90 days) to save space
        cleanup_threshold = timezone.now() - timedelta(days=90)
        deleted_count, _ = ContentViewEvent.objects.filter(
            timestamp__lt=cleanup_threshold
        ).delete()
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old view events (older than 90 days)")
        
        return {
            'date': str(yesterday),
            'aggregated': aggregated_count,
            'cleaned_up': deleted_count
        }
        
    except Exception as exc:
        logger.error(f"Error in aggregate_daily_content_views: {str(exc)}", exc_info=True)
        raise


# ============================================================================
# API Upload Queue Processing Tasks
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_upload_queue_item(self, queue_item_id):
    """
    Process a queue item from the API upload queue.
    Creates ContentItem and triggers media processing pipeline.
    Handles Gemini rate limits by scheduling for next day at 3:00 AM.
    
    Args:
        queue_item_id: UUID string of APIUploadQueue item
    """
    logger = logging.getLogger(__name__)
    
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    from apps.media_manager.models import APIUploadQueue
    
    try:
        queue_item = APIUploadQueue.objects.get(id=queue_item_id)
    except APIUploadQueue.DoesNotExist:
        logger.error(f'Queue item {queue_item_id} not found')
        return
    
    logger.info(f'Processing queue item {queue_item_id} ({queue_item.file_name})')
    
    try:
        # Process the queue item
        content_item = APIUploadQueueService.process_queue_item(queue_item_id)
        
        if content_item:
            logger.info(f'Successfully created ContentItem {content_item.id} from queue item {queue_item_id}')
        else:
            logger.warning(f'Failed to create ContentItem from queue item {queue_item_id}')
    
    except Exception as e:
        # Check if it's a Gemini rate limit error
        if 'rate' in str(e).lower() and 'limit' in str(e).lower():
            logger.warning(f'Gemini rate limit hit for queue item {queue_item_id}')
            APIUploadQueueService.handle_rate_limit_exceeded(queue_item)
        else:
            logger.error(f'Error processing queue item {queue_item_id}: {e}', exc_info=True)
            
            # Update queue item with error
            queue_item.status = 'failed'
            queue_item.error_message = str(e)
            queue_item.gemini_attempts += 1
            queue_item.save(update_fields=['status', 'error_message', 'gemini_attempts', 'updated_at'])
            
            # Release lock
            APIUploadQueueService.release_processing_lock(queue_item.content_type)
            
            # Retry if not exceeded max retries
            if queue_item.gemini_attempts < 3:
                raise self.retry(exc=e, countdown=300)  # Retry after 5 minutes


@shared_task
def process_scheduled_queue_items():
    """
    Periodic task to process items scheduled for current time.
    Runs every hour via Celery Beat.
    Respects content type concurrency limits.
    """
    logger = logging.getLogger(__name__)
    from django.utils import timezone
    from apps.media_manager.models import APIUploadQueue
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    
    now = timezone.now()
    logger.info(f'Processing scheduled queue items at {now}')
    
    # Find items scheduled for now or past
    scheduled_items = APIUploadQueue.objects.filter(
        status__in=['queued', 'rate_limited'],
        scheduled_for__lte=now,
        delay_count__lt=7
    ).order_by('-priority', 'scheduled_for')
    
    processed_types = set()
    processed_count = 0
    
    for item in scheduled_items:
        # Only process one item per content type
        if item.content_type in processed_types:
            continue
        
        # Check if can process this type
        if APIUploadQueueService.can_process_type(item.content_type):
            item.queue_status = 'ready'
            item.status = 'queued'
            item.save(update_fields=['queue_status', 'status', 'updated_at'])
            
            # Trigger processing
            process_upload_queue_item.delay(str(item.id))
            
            processed_types.add(item.content_type)
            processed_count += 1
            logger.info(f'Triggered processing for scheduled item {item.id}')
    
    logger.info(f'Processed {processed_count} scheduled items')
    return processed_count


@shared_task
def process_delayed_3am_queue():
    """
    Scheduled task to process items delayed for 3:00 AM.
    Runs daily at 3:00 AM via Celery Beat.
    Processes all items scheduled for current day.
    """
    logger = logging.getLogger(__name__)
    from django.utils import timezone
    from apps.media_manager.models import APIUploadQueue
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    
    now = timezone.now()
    logger.info(f'Processing 3:00 AM delayed queue at {now}')
    
    # Find items scheduled for today
    today = now.date()
    scheduled_items = APIUploadQueue.objects.filter(
        status='rate_limited',
        queue_status='delayed',
        scheduled_for__date=today,
        delay_count__lt=7
    ).order_by('-priority', 'created_at')
    
    processed_types = set()
    processed_count = 0
    
    for item in scheduled_items:
        # Only process one item per content type at a time
        if item.content_type in processed_types:
            continue
        
        # Check if can process this type
        if APIUploadQueueService.can_process_type(item.content_type):
            item.queue_status = 'ready'
            item.status = 'queued'
            item.save(update_fields=['queue_status', 'status', 'updated_at'])
            
            # Trigger processing
            process_upload_queue_item.delay(str(item.id))
            
            processed_types.add(item.content_type)
            processed_count += 1
            logger.info(f'Triggered 3 AM processing for item {item.id}')
    
    logger.info(f'Processed {processed_count} delayed items at 3:00 AM')
    return processed_count


@shared_task
def cleanup_expired_queue_items():
    """
    Daily task to cleanup queue items that have exceeded delay limit.
    Cancels items with delay_count >= 7.
    Cleans up temporary files.
    """
    logger = logging.getLogger(__name__)
    from apps.media_manager.models import APIUploadQueue
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    
    logger.info('Cleaning up expired queue items')
    
    # Find items that exceeded delay limit
    expired_items = APIUploadQueue.objects.filter(
        delay_count__gte=7,
        status__in=['rate_limited', 'queued', 'pending']
    )
    
    cancelled_count = 0
    for item in expired_items:
        item.status = 'cancelled'
        item.error_message = 'Cancelled after 7 days of rate limit delays'
        item.save(update_fields=['status', 'error_message', 'updated_at'])
        
        # Clean up temp files
        APIUploadQueueService._cleanup_temp_files(item)
        cancelled_count += 1
        
        logger.info(f'Cancelled expired queue item {item.id}')
    
    logger.info(f'Cancelled {cancelled_count} expired queue items')
    return cancelled_count


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_document_text(self, contentitem_id, user_id=None):
    """
    Extract text from supplementary document and update search index.
    Retries up to 3 times with 60 second delays on failure.
    Includes task monitoring for admin dashboard.
    
    Workflow:
    1. Fetch ContentItem
    2. Check if supplementary document exists
    3. Extract text using appropriate method
    4. Clean and normalize text
    5. Save to supplementary_document_text
    6. Update search_vector
    7. Save ContentItem
    
    Args:
        contentitem_id: UUID of the ContentItem
        user_id: Optional user ID for task monitoring
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    # Register task for monitoring
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='Document Text Extraction',
        user_id=user_id,
        metadata={'content_id': contentitem_id}
    )
    
    try:
        logger.info(f"Starting document text extraction for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Check if document exists
        if not item.supplementary_document or not item.supplementary_document.name:
            logger.warning(f"ContentItem {contentitem_id} has no supplementary document")
            TaskMonitor.update_task_status(
                self.request.id,
                'SUCCESS',
                {'message': 'No supplementary document to process'}
            )
            return
        
        TaskMonitor.update_progress(
            self.request.id,
            10,
            'Extracting text from supplementary document...',
            'Text extraction'
        )
        
        # Extract text from document
        item.extract_text_from_document()
        
        # Save the extracted content to both supplementary_document_text AND book_content
        # Overwrite book_content with document content as requested
        if item.supplementary_document_text:
            item.book_content = item.supplementary_document_text
            item.save(update_fields=['supplementary_document_text', 'book_content'])
            logger.info(f"Overwrote book_content with document text for ContentItem {contentitem_id}")
        else:
            item.save(update_fields=['supplementary_document_text'])
            logger.warning(f"No text extracted from document for ContentItem {contentitem_id}")
        
        TaskMonitor.update_progress(
            self.request.id,
            70,
            'Updating search index with document text...',
            'Search indexing'
        )
        
        # Update search vector using UPDATE query to properly evaluate SearchVector expression
        from django.contrib.postgres.search import SearchVector
        
        # Build search vector parts based on available content
        search_parts = []
        
        if item.book_content:
            search_parts.append(SearchVector('book_content', weight='A', config='arabic'))
        
        if item.transcript:
            search_parts.append(SearchVector('transcript', weight='A', config='simple'))
        
        if item.supplementary_document_text:
            search_parts.append(SearchVector('supplementary_document_text', weight='B', config='arabic'))
        
        if item.description_ar:
            search_parts.append(SearchVector('description_ar', weight='B', config='arabic'))
        
        if item.description_en:
            search_parts.append(SearchVector('description_en', weight='B', config='english'))
        
        if item.title_ar:
            search_parts.append(SearchVector('title_ar', weight='C', config='arabic'))
        
        if item.title_en:
            search_parts.append(SearchVector('title_en', weight='C', config='english'))
        
        if item.notes:
            search_parts.append(SearchVector('notes', weight='D', config='simple'))
        
        # Combine and update
        if search_parts:
            combined_vector = search_parts[0]
            for part in search_parts[1:]:
                combined_vector += part
            ContentItem.objects.filter(id=item.id).update(search_vector=combined_vector)
        
        extracted_length = len(item.supplementary_document_text) if item.supplementary_document_text else 0
        logger.info(f"Successfully extracted and indexed document text for ContentItem {contentitem_id}: {extracted_length} characters")
        
        # Mark task as successful
        TaskMonitor.update_task_status(
            self.request.id,
            'SUCCESS',
            {
                'message': 'Document text successfully indexed for search',
                'extracted_chars': extracted_length,
                'progress': 100
            }
        )
        
    except ContentItem.DoesNotExist:
        error_msg = f"ContentItem {contentitem_id} not found"
        logger.error(error_msg)
        TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=error_msg)
        return
        
    except Exception as exc:
        error_msg = f"Error processing document for ContentItem {contentitem_id}: {str(exc)}"
        logger.error(error_msg, exc_info=True)
        
        TaskMonitor.update_task_status(
            self.request.id,
            'RETRY',
            {'message': f'Retry {self.request.retries + 1}/3', 'error': str(exc)}
        )
        
        # Retry the task with exponential backoff
        try:
            self.retry(countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for ContentItem {contentitem_id}")
            TaskMonitor.update_task_status(
                self.request.id,
                'FAILURE',
                {'message': 'Failed after 3 retries', 'error': str(exc), 'progress': 100}
            )


