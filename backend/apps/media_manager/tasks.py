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


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def generate_seo_metadata_task(self, contentitem_id):
    """
    Generate SEO metadata for content using Gemini AI.
    Retries up to 3 times with 2-minute delays on failure.
    """
    logger = logging.getLogger(__name__)
    ContentItem = get_contentitem_model()
    
    try:
        logger.info(f"Starting SEO metadata generation for ContentItem {contentitem_id}")
        
        item = ContentItem.objects.get(id=contentitem_id)
        
        # Get the media file path
        meta = item.get_meta_object()
        if not meta or not hasattr(meta, 'original_file') or not meta.original_file:
            logger.warning(f"No media file found for ContentItem {contentitem_id}")
            return
        
        file_path = meta.original_file.path
        
        # Import Gemini service
        from apps.media_manager.services.gemini_service import get_gemini_service
        
        # Generate SEO metadata
        service = get_gemini_service()
        if not service.is_available():
            logger.error("Gemini AI service not available")
            raise Exception("Gemini AI service not available")
        
        success, seo_metadata = service.generate_seo_metadata(file_path, item.content_type)
        
        if success and seo_metadata:
            # Update the content item with SEO metadata
            success_update = item.update_seo_from_gemini(seo_metadata)
            
            if success_update:
                logger.info(f"Successfully generated and updated SEO metadata for ContentItem {contentitem_id}")
                
                # Log SEO metadata statistics
                keyword_count = len(seo_metadata.get('seo_keywords_ar', [])) + len(seo_metadata.get('seo_keywords_en', []))
                logger.info(f"SEO stats for {contentitem_id}: {keyword_count} keywords, "
                          f"meta descriptions: AR({len(seo_metadata.get('seo_meta_description_ar', ''))}), "
                          f"EN({len(seo_metadata.get('seo_meta_description_en', ''))})")
            else:
                logger.error(f"Failed to update SEO metadata for ContentItem {contentitem_id}")
        else:
            error_msg = seo_metadata.get('error', 'Unknown error') if isinstance(seo_metadata, dict) else 'Generation failed'
            logger.error(f"Failed to generate SEO metadata for ContentItem {contentitem_id}: {error_msg}")
            raise Exception(f"SEO generation failed: {error_msg}")
        
    except ContentItem.DoesNotExist:
        logger.error(f"ContentItem {contentitem_id} not found")
        return
        
    except Exception as exc:
        logger.error(f"Error generating SEO metadata for ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        
        # Retry with exponential backoff
        try:
            self.retry(countdown=120 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for SEO generation of ContentItem {contentitem_id}")


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
