from celery import shared_task
from django.apps import apps
import logging

def get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_and_index_contentitem(self, contentitem_id):
    """
    Extract text from PDF and update search index.
    Retries up to 3 times with 60 second delays on failure.
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    try:
        logger.info(f"Starting extraction and indexing for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Only process PDFs
        if item.content_type != 'pdf':
            logger.warning(f"ContentItem {contentitem_id} is not a PDF, skipping extraction")
            return
        
        # Extract text from PDF (includes OCR fallback)
        item.extract_text_from_pdf()
        
        # Update search vector
        item.update_search_vector()
        
        # Save changes
        item.save(update_fields=["book_content", "search_vector"])
        
        extracted_length = len(item.book_content) if item.book_content else 0
        logger.info(f"Successfully completed extraction and indexing for ContentItem {contentitem_id}: {extracted_length} characters")
        
    except ContentItem.DoesNotExist:
        logger.error(f"ContentItem {contentitem_id} not found")
        # Don't retry for non-existent items
        return
        
    except Exception as exc:
        logger.error(f"Error processing ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        
        # Retry the task with exponential backoff
        try:
            self.retry(countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for ContentItem {contentitem_id}")
