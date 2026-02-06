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
    
    # Register task for monitoring
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='PDF Text Extraction',
        user_id=user_id,
        metadata={'content_id': contentitem_id, 'content_type': 'pdf'}
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
        
        # Update task status to indicate processing has started
        item.processing_status = 'processing'
        item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_progress(
            self.request.id, 
            10,
            'Transcribing sacred text content for search capabilities...', 
            'Text extraction'
        )
        
        # Extract text from PDF (includes OCR fallback)
        item.extract_text_from_pdf()
        
        # Save the extracted content first
        item.save(update_fields=["book_content"])
        
        TaskMonitor.update_progress(
            self.request.id, 
            70,
            'Updating internal library search engines...', 
            'Search indexing'
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
        
        extracted_length = len(item.book_content) if item.book_content else 0
        logger.info(f"Successfully completed extraction and indexing for ContentItem {contentitem_id}: {extracted_length} characters")
        
        # Mark task as successful
        TaskMonitor.update_task_status(
            self.request.id, 
            'SUCCESS', 
            {
                'message': 'Sacred text successfully indexed for search',
                'extracted_chars': extracted_length,
                'progress': 100
            }
        )
        
        # Parallel Trigger: Trigger SEO generation and R2 upload at the same time
        if item.content_type in ['video', 'audio', 'pdf']:
            TaskMonitor.update_progress(self.request.id, 95, "Extraction complete. Starting AI enrichment and cloud delivery...", "Finalizing")
            
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


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_seo_metadata_task(self, contentitem_id):
    """
    Generate SEO metadata for content using Gemini AI.
    Retries up to 2 times with 2-minute delays on failure.
    Now decoupled from R2 upload and activation.
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    # Register task for monitoring
    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='AI SEO Metadata Generation',
        metadata={'content_id': contentitem_id, 'attempt': self.request.retries + 1}
    )
    
    try:
        logger.info(f"Starting SEO metadata generation for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Update SEO status to processing
        item.seo_processing_status = 'processing'
        item.save(update_fields=['seo_processing_status'])
        
        TaskMonitor.update_progress(
            self.request.id, 
            10,
            'Preparing content for AI analysis...', 
            'Initialization'
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
            f'Generating SEO metadata with AI (attempt {self.request.retries + 1}/{self.max_retries + 1})...', 
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
                # Mark processing as completed
                item.seo_processing_status = 'completed'
                # If it's a video or audio, we also mark the main processing status as completed
                # (For PDF, it's marked completed after optimization but before OCR/SEO)
                if item.content_type in ['video', 'audio']:
                    item.processing_status = 'completed'
                
                item.save(update_fields=['seo_processing_status', 'processing_status'])
                
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
        logger.error(f"Error generating SEO metadata for ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        
        # Check if max retries exceeded (this is attempt self.request.retries + 1 of max_retries + 1)
        is_last_attempt = self.request.retries >= self.max_retries
        
        # Update task monitor with retry status
        TaskMonitor.update_task_status(
            self.request.id, 
            'RETRY' if not is_last_attempt else 'FAILURE',
            {
                'message': f'Attempt {self.request.retries + 1}/{self.max_retries + 1} failed: {str(exc)}',
                'progress': 100 if is_last_attempt else 50
            }
        )
        
        # Retry with exponential backoff
        try:
            self.retry(countdown=120 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries (2) exceeded for SEO generation of ContentItem {contentitem_id}. Marking as failed with progress 100%.")
            try:
                item = ContentItem.objects.get(id=contentitem_id)
                item.seo_processing_status = 'failed'
                item.save(update_fields=['seo_processing_status'])
                # Ensure task is marked as failed with 100% progress to unblock UI
                TaskMonitor.update_task_status(
                    self.request.id, 
                    'FAILURE', 
                    {
                        'message': f'AI service failed after 2 retries. Manual review required.',
                        'progress': 100,
                        'error': str(exc)
                    }
                )
            except:
                pass


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
                
                if local_paths:
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
