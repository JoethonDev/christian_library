import os
from datetime import datetime, timedelta
from celery import shared_task
from django.apps import apps
from django.contrib.postgres.search import SearchVector
from django.db.models import Count
from django.utils import timezone
from apps.health.task_monitor import TaskMonitor
import logging
from apps.media_manager.services.job_tracker import job_advance, job_complete, job_fail, job_start
from apps.media_manager.models import ContentViewEvent, DailyContentViewSummary, APIUploadQueue
from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
from core.tasks.media_processing import upload_pdf_to_r2
from core.tasks.media_finalization import delete_files_task, generate_seo_metadata_task, finalize_media_processing, bulk_generate_seo_metadata

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

            meta = item.get_meta_object()
            if meta:
                upload_pdf_to_r2.delay(str(meta.id))
                generate_seo_metadata_task.delay(str(item.id))
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
            queue_item.save(update_fields=['status', 'error_message', 'updated_at'])
            
            # Release lock
            APIUploadQueueService.release_processing_lock(queue_item.content_type)
            
            # Retry (Celery's max_retries handles the limit)
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


