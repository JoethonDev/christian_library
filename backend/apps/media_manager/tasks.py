import os
from datetime import datetime, timedelta
from pathlib import Path
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from apps.health.task_monitor import TaskMonitor
import logging
from core.services.gemini_manager import get_gemini_manager
from apps.media_manager.services.job_tracker import job_advance, job_complete, job_fail, job_start
from apps.media_manager.models import ContentViewEvent, DailyContentViewSummary, APIUploadQueue
from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService

logger = logging.getLogger(__name__)

def get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_and_index_contentitem(self, contentitem_id, user_id=None):
    """
    Extract text from PDF and update search index.
    Retries up to 3 times with 60 second delays on failure.
    Now includes task monitoring for admin dashboard.
    """
    ContentItem = get_contentitem_model()
    
    # Register task for monitoring with checklist tracking
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='PDF Text Extraction',
        user_id=user_id,
        metadata={'content_id': contentitem_id, 'content_type': 'pdf'},
        checklist_steps=['text_extraction', 'search_indexing', 'finalization']
    )
    job_start(contentitem_id, 'text_extraction', self.request.id)
    
    try:
        logger.info(f"Starting extraction and indexing for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Only process PDFs
        if item.content_type != 'pdf':
            logger.warning(f"ContentItem {contentitem_id} is not a PDF, skipping extraction")
            job_complete(contentitem_id)
            TaskMonitor.update_task_status(
                self.request.id, 
                'SUCCESS', 
                {'message': 'Skipped - not a PDF'}
            )
            return
        
        # Update task status to indicate processing has started (only if not already completed)
        # For PDFs, file processing completes first, then text extraction happens.
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
        job_advance(contentitem_id, 'r2_upload')
        
        extracted_length = len(item.book_content) if item.book_content else 0
        logger.info(f"Successfully completed extraction and indexing for ContentItem {contentitem_id}: {extracted_length} characters")
        
        # Trigger downstream work after extraction finishes.
        if item.content_type in ['video', 'audio']:
            TaskMonitor.update_progress(
                self.request.id, 
                message="Starting AI enrichment and cloud delivery...", 
                step="finalization"
            )
        elif item.content_type == 'pdf':
            TaskMonitor.update_progress(
                self.request.id,
                message="Starting cloud delivery for extracted PDF...",
                step="finalization"
            )

            from core.tasks.media_processing import upload_pdf_to_r2
            meta = item.get_meta_object()
            if meta:
                upload_pdf_to_r2.delay(str(meta.id))
                logger.info(f"Triggered R2 upload for PDF: {meta.id}")
        
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
        job_fail(contentitem_id, 'text_extraction', error_msg)
        TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=error_msg)
        # Don't retry for non-existent items
        return
        
    except Exception as exc:
        error_msg = f"Error processing ContentItem {contentitem_id}: {str(exc)}"
        logger.error(error_msg, exc_info=True)
        job_fail(contentitem_id, 'text_extraction', exc)
        
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
    job_start(contentitem_id, 'seo_generation', self.request.id)
    from apps.media_manager.services.lifecycle_audit_service import LifecycleAuditService
    
    try:
        logger.info(f"🔄 Starting SEO metadata generation for ContentItem {contentitem_id} (attempt {self.request.retries + 1}/{self.max_retries + 1}, force={force_regenerate})")
        
        TaskMonitor.update_progress(
            self.request.id, 
            message='Validating content item...', 
            step='validation'
        )
        
        item = ContentItem.objects.get(id=contentitem_id)

        LifecycleAuditService.log_event(
            content_item=item,
            action_type='gemini_processing_started',
            source='system:seo_task',
            previous_state='pending',
            new_state='processing',
            message='Gemini SEO generation task started',
            payload={'content_id': str(item.id), 'task_id': self.request.id, 'force': force_regenerate},
        )
        
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
        
        # Get the media file path, or fall back to extracted text if the file has already been cleaned up.
        meta = item.get_meta_object()
        context_text = item.book_content if item.book_content else None
        file_path = None

        if meta and hasattr(meta, 'original_file') and meta.original_file:
            file_path = meta.original_file.path
            if not os.path.exists(file_path):
                if not context_text:
                    logger.warning(f"Media file not found at {file_path}")
                    item.seo_processing_status = 'failed'
                    item.save(update_fields=['seo_processing_status'])
                    TaskMonitor.update_task_status(
                        self.request.id,
                        'FAILURE',
                        {'message': 'Media file not found on disk', 'progress': 100}
                    )
                    return
                file_path = None
        elif not context_text:
            logger.warning(f"No media file found for ContentItem {contentitem_id}")
            item.seo_processing_status = 'failed'
            item.save(update_fields=['seo_processing_status'])
            TaskMonitor.update_task_status(
                self.request.id,
                'FAILURE',
                {'message': 'No media file found', 'progress': 100}
            )
            return

        TaskMonitor.update_progress(
            self.request.id, 
            30,
            'Connecting to AI service...', 
            'AI Service'
        )
        
        # Generate combined metadata + SEO in one Gemini call
        manager = get_gemini_manager()
        
        TaskMonitor.update_progress(
            self.request.id, 
            50,
            f'Generating combined metadata and SEO with AI (attempt {self.request.retries + 1}/3)...', 
            'AI Processing'
        )
        
        success, combined_data = manager.generate_combined_ai_data(file_path, item.content_type, context_text=context_text)
        
        if success and combined_data:
            TaskMonitor.update_progress(
                self.request.id, 
                80,
                'Updating content with AI-generated metadata...', 
                'Saving'
            )
            
            # Update the content item with combined metadata + SEO
            success_update = item.update_combined_ai_data(combined_data)
            
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

                LifecycleAuditService.log_event(
                    content_item=item,
                    action_type='gemini_processing_completed',
                    source='system:seo_task',
                    previous_state='processing',
                    new_state='completed',
                    message='Gemini SEO generation task completed',
                    payload={'content_id': str(item.id), 'task_id': self.request.id, 'force': force_regenerate},
                )
                
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
                job_fail(contentitem_id, 'seo_generation', 'Failed to save AI-generated metadata')
                TaskMonitor.update_task_status(
                    self.request.id, 
                    'FAILURE', 
                    {'message': 'Failed to save AI-generated metadata', 'progress': 100}
                )
        else:
            error_msg = combined_data.get('error', 'Unknown error') if isinstance(combined_data, dict) else 'Generation failed'
            logger.error(f"Failed to generate SEO metadata for ContentItem {contentitem_id}: {error_msg}")
            raise Exception(f"Combined AI generation failed: {error_msg}")
        
    except ContentItem.DoesNotExist:
        logger.error(f"ContentItem {contentitem_id} not found")
        job_fail(contentitem_id, 'seo_generation', 'Content not found')
        TaskMonitor.update_task_status(
            self.request.id, 
            'FAILURE', 
            {'message': 'Content not found', 'progress': 100}
        )
        return
        
    except Exception as exc:
        logger.error(f"💥 Error generating SEO metadata for ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        job_fail(contentitem_id, 'seo_generation', exc)

        # Helper: permanently mark SEO as failed and trigger finalize so local files
        # are still cleaned up and the job record is closed properly.
        def _seo_permanently_failed(reason: str):
            try:
                _item = ContentItem.objects.get(id=contentitem_id)
                _item.seo_processing_status = 'failed'
                _item.save(update_fields=['seo_processing_status'])
            except Exception:
                pass
            job_fail(contentitem_id, 'seo_generation', reason)
            finalize_media_processing.delay(str(contentitem_id))
            TaskMonitor.update_task_status(
                self.request.id,
                'FAILURE',
                {'message': reason, 'progress': 100},
            )
            logger.error(f"SEO permanently failed for {contentitem_id}: {reason}")

        # Enhanced error detection
        is_rate_limit_error = _is_gemini_rate_limit_error(exc)
        is_server_error = _is_gemini_server_error(exc)

        # Plan logic:
        # 1. Any error after 3 failed attempts (retries 0, 1, 2) -> schedule for next day 3 AM
        # 2. Server errors (5xx) -> retry after 10 mins (600s)
        # 3. Other errors -> retry with current default or rate limit logic

        if self.request.retries >= 2:  # 0, 1, 2 attempts failed
            next_3am_delay = _calculate_next_3am_delay()
            logger.warning(f"❌ 3 attempts failed for ContentItem {contentitem_id}. Scheduling next attempt for 3:00 AM.")
            try:
                item.seo_processing_status = 'failed'
                item.save(update_fields=['seo_processing_status'])
            except Exception:
                pass

            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'3 attempts failed - rescheduling for 3:00 AM (Error: {str(exc)[:100]})',
                    'retry_at': '3:00 AM',
                    'delay_hours': round(next_3am_delay / 3600, 1),
                },
            )
            try:
                raise self.retry(exc=exc, countdown=next_3am_delay)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('All retries exhausted for SEO generation (3AM schedule)')
                return {'status': 'failed', 'message': 'Max retries exhausted'}

        if is_server_error:
            logger.warning(f"🔌 Gemini server error detected (5xx) for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            countdown = 600  # 10 minutes
            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'Server error (5xx) - retrying in 10 minutes (attempt {self.request.retries + 1}/3)',
                    'countdown': countdown,
                    'error_type': 'server',
                },
            )
            try:
                raise self.retry(exc=exc, countdown=countdown)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('Max retries exceeded for SEO generation (server error path)')
                return {'status': 'failed', 'message': 'Max retries exceeded'}

        if is_rate_limit_error:
            logger.warning(f"🚦 Gemini rate limit detected for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            countdown = 300  # 5 minutes before 3rd attempt
            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'Rate limited - retrying in 5 minutes (attempt {self.request.retries + 1}/3)',
                    'rate_limited': True,
                    'countdown': countdown,
                },
            )
            try:
                raise self.retry(exc=exc, countdown=countdown)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('Max retries exceeded for SEO generation (rate limit path)')
                return {'status': 'failed', 'message': 'Max retries exceeded'}

        # Standard fallback for other errors
        countdown = 120 * (2 ** self.request.retries)
        logger.info(f"🔄 Standard retry for ContentItem {contentitem_id} in {countdown}s (attempt {self.request.retries + 1})")
        TaskMonitor.update_task_status(
            self.request.id,
            'RETRY',
            {
                'message': f'Error retry in {countdown}s (attempt {self.request.retries + 1}/3)',
                'countdown': countdown,
                'error_type': 'standard',
            },
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            _seo_permanently_failed('Max retries exceeded for SEO generation (standard path)')
            return {'status': 'failed', 'message': 'Max retries exceeded'}

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


@shared_task(bind=True, max_retries=8, default_retry_delay=600)
def finalize_media_processing(self, contentitem_id):
    """
    Check if both R2 upload and SEO generation are finished.
    If both are done, safe to delete local files.
    Retries up to 8 times (every 10 min) so a delayed SEO result is still caught.
    """
    ContentItem = get_contentitem_model()

    try:
        item = ContentItem.objects.get(id=contentitem_id)
        meta = item.get_meta_object()

        if not meta:
            logger.warning(f"finalize_media_processing: no meta for {contentitem_id}, completing job anyway")
            job_complete(contentitem_id)
            return

        # Condition 1: R2 upload completed successfully.
        r2_done = meta.r2_upload_status == 'completed'

        # Condition 2: SEO generation completed successfully.
        # 'failed' does NOT satisfy this condition — if SEO failed or stalled,
        # local files must be preserved (they are the only remaining copy).
        seo_done = item.seo_processing_status == 'completed'

        if r2_done and seo_done:
            logger.info(f"Both R2 and SEO finished for {contentitem_id}. Cleaning up local files.")

            local_paths = []
            try:
                # Original file
                if meta.original_file and os.path.exists(meta.original_file.path):
                    local_paths.append(str(meta.original_file.path))

                # Content-type specific processed files
                if item.content_type == 'video':
                    hls_dir = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / str(item.id)
                    if hls_dir.exists():
                        local_paths.append(str(hls_dir))
                elif item.content_type == 'audio':
                    if hasattr(meta, 'compressed_file') and meta.compressed_file and os.path.exists(meta.compressed_file.path):
                        local_paths.append(str(meta.compressed_file.path))

                if local_paths:
                    from core.tasks.media_processing import delete_files_task
                    delete_files_task.delay(local_paths)
                    logger.info(f"Queued deletion for {len(local_paths)} paths for item {item.id}")
                else:
                    logger.info(f"No local files to delete for item {item.id} (already cleaned or never written)")

                job_complete(contentitem_id)

            except Exception as e:
                logger.warning(f"Error preparing local files for deletion for item {item.id}: {e}")
                job_complete(contentitem_id)

        else:
            # One or both conditions not yet met — reschedule so we catch them later.
            logger.info(
                f"Finalize deferred for {contentitem_id}: R2={r2_done}, SEO={seo_done} "
                f"(attempt {self.request.retries + 1}/{self.max_retries + 1})"
            )
            try:
                raise self.retry(countdown=600)
            except self.MaxRetriesExceededError:
                logger.warning(
                    f"finalize_media_processing max retries reached for {contentitem_id}: "
                    f"R2={r2_done}, SEO={seo_done}. Completing job without full cleanup."
                )
                job_complete(contentitem_id)

    except ContentItem.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error in finalize_media_processing: {str(e)}")
        try:
            job_fail(contentitem_id, 'completed', e)
        except Exception:
            pass


@shared_task
def bulk_generate_seo_metadata(content_type=None, limit=None):
    """
    Generate SEO metadata for content items that don't have it yet.
    
    Args:
        content_type: Optional filter by content type ('video', 'audio', 'pdf')
        limit: Optional limit on number of items to process
    """
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
    
    
    try:
        # Process events from yesterday
        yesterday = timezone.now().date() - timedelta(days=1)
        start_datetime = datetime.combine(yesterday, datetime.min.time())
        end_datetime = datetime.combine(yesterday, datetime.max.time())
        
        # Make datetimes timezone-aware
        start_datetime = timezone.make_aware(start_datetime)
        end_datetime = timezone.make_aware(end_datetime)
        
        logger.info(f"Aggregating view events for {yesterday}")
        
        # Aggregate total and unique views in one grouped query.
        events = ContentViewEvent.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        ).values('content_type', 'content_id').annotate(
            count=Count('id'),
            unique_views=Count('ip_address', distinct=True),
        )
        
        aggregated_count = 0
        for event_data in events:
            total_views = event_data['count']
            unique_views = event_data['unique_views']
            
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
def process_upload_queue_item(self, queue_item_id, trigger_next=True):
    """
    Process a queue item from the API upload queue.
    Creates ContentItem and triggers media processing pipeline.
    Handles Gemini rate limits by scheduling for next day at 3:00 AM.
    
    Args:
        queue_item_id: UUID string of APIUploadQueue item
    """
    
    
    try:
        queue_item = APIUploadQueue.objects.get(id=queue_item_id)
    except APIUploadQueue.DoesNotExist:
        logger.error(f'Queue item {queue_item_id} not found')
        return
    
    logger.info(f'Processing queue item {queue_item_id} ({queue_item.file_name})')
    
    try:
        # Process the queue item
        content_item = APIUploadQueueService.process_queue_item(queue_item_id, trigger_next=trigger_next)
        
        if content_item:
            job_start(content_item.id, 'file_processing', self.request.id)
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
def process_pending_queue_items(include_rate_limited=False):
    """
    Periodic task to process items scheduled for current time.
    Runs every hour via Celery Beat, and again at 3:00 AM with rate-limited items.
    Respects content type concurrency limits.
    """

    now = timezone.now()
    logger.info(
        f'Processing pending queue items at {now} (include_rate_limited={include_rate_limited})'
    )

    status_filter = ['queued']
    if include_rate_limited:
        status_filter.append('rate_limited')

    scheduled_items = APIUploadQueue.objects.filter(
        status__in=status_filter,
        scheduled_for__lte=now,
        delay_count__lt=7,
    ).order_by('-priority', 'scheduled_for', 'created_at')

    processed_types = set()
    processed_count = 0

    for item in scheduled_items:
        if item.content_type in processed_types:
            continue

        if APIUploadQueueService.can_process_type(item.content_type):
            item.queue_status = 'ready'
            item.status = 'queued'
            item.save(update_fields=['queue_status', 'status', 'updated_at'])

            process_upload_queue_item.delay(str(item.id))

            processed_types.add(item.content_type)
            processed_count += 1
            logger.info(f'Triggered processing for pending item {item.id}')

    logger.info(f'Processed {processed_count} pending queue items')
    return processed_count


@shared_task
def cleanup_expired_queue_items():
    """
    Daily task to cleanup queue items that have exceeded delay limit.
    Cancels items with delay_count >= 7.
    Cleans up temporary files.
    """
    
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


