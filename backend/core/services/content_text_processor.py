"""
High-Performance Batch Text Processing Service

Integrates Arabic text cleaning with Django models and provides
efficient batch processing for large-scale content operations.
"""

import logging
from typing import Dict, List, Optional, Tuple
from django.db import transaction, connection, models
from django.conf import settings
import time
import gc

from core.utils.arabic_text_processor import ArabicTextProcessor
from apps.media_manager.models import ContentItem

logger = logging.getLogger(__name__)


class ContentTextProcessor:
    """
    High-performance service for processing ContentItem text with Arabic cleaning.
    Designed for efficient batch operations on large collections.
    """
    
    def __init__(self, batch_size: int = 100, max_workers: Optional[int] = None):
        """
        Initialize content processor.
        
        Args:
            batch_size: Number of items to process per database batch
            max_workers: Number of worker processes for multiprocessing
        """
        self.batch_size = batch_size
        self.processor = ArabicTextProcessor(max_workers)
        self.stats = {
            'items_processed': 0,
            'items_updated': 0,
            'total_chars_processed': 0,
            'total_processing_time': 0.0,
            'errors': []
        }
    
    def process_content_item(self, content_item: ContentItem, update_db: bool = True) -> Dict[str, any]:
        """
        Process a single ContentItem with Arabic text cleaning.
        
        Args:
            content_item: ContentItem instance to process
            update_db: Whether to save changes to database
            
        Returns:
            Processing results with cleaned text and statistics
        """
        start_time = time.time()
        
        try:
            # Skip if no book content
            if not content_item.book_content or len(content_item.book_content.strip()) < 10:
                logger.debug(f"Skipping {content_item.id}: No meaningful text content")
                return {
                    'content_id': str(content_item.id),
                    'success': False,
                    'reason': 'No meaningful text content',
                    'stats': None
                }
            
            # Process the text
            result = self.processor.process_single_document(content_item.book_content)
            
            if update_db:
                # Update the content item
                content_item.book_content = result['cleaned_text']
                
                # Create search-ready field if using SQLite (for development)
                # In production with PostgreSQL, this would update the search_vector
                if hasattr(content_item, 'book_content_search'):
                    content_item.book_content_search = result['search_text']
                
                # Update search vector for PostgreSQL
                if 'postgresql' in settings.DATABASES['default']['ENGINE']:
                    content_item.update_search_vector()
                
                content_item.save(update_fields=['book_content', 'search_vector', 'updated_at'])
                
                logger.info(
                    f"Processed {content_item.id}: "
                    f"{result['stats'].original_length} → {result['stats'].cleaned_length} chars "
                    f"({result['stats'].compression_ratio:.1f}% compression)"
                )
            
            processing_time = time.time() - start_time
            
            return {
                'content_id': str(content_item.id),
                'success': True,
                'cleaned_text': result['cleaned_text'],
                'search_text': result['search_text'],
                'stats': result['stats'],
                'processing_time': processing_time
            }
            
        except Exception as e:
            error_msg = f"Error processing {content_item.id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.stats['errors'].append(error_msg)
            
            return {
                'content_id': str(content_item.id),
                'success': False,
                'reason': str(e),
                'stats': None,
                'processing_time': time.time() - start_time
            }
    
    def process_content_batch(self, content_items: List[ContentItem]) -> List[Dict[str, any]]:
        """
        Process a batch of ContentItem instances efficiently.
        
        Args:
            content_items: List of ContentItem instances
            
        Returns:
            List of processing results
        """
        logger.info(f"Processing batch of {len(content_items)} content items")
        
        results = []
        
        with transaction.atomic():
            for item in content_items:
                result = self.process_content_item(item, update_db=True)
                results.append(result)
                
                # Update statistics
                if result['success']:
                    self.stats['items_updated'] += 1
                    if result['stats']:
                        self.stats['total_chars_processed'] += result['stats'].original_length
                
                self.stats['items_processed'] += 1
        
        return results
    
    def process_all_pdfs(self, 
                         content_type: str = 'pdf',
                         force_reprocess: bool = False,
                         dry_run: bool = False) -> Dict[str, any]:
        """
        Process all PDF content items with Arabic text cleaning.
        
        Args:
            content_type: Type of content to process ('pdf', 'all')
            force_reprocess: Reprocess items even if already processed
            dry_run: Don't save changes, just report what would be done
            
        Returns:
            Processing summary with statistics
        """
        start_time = time.time()
        
        # Build queryset
        queryset = ContentItem.objects.filter(is_active=True)
        
        if content_type != 'all':
            queryset = queryset.filter(content_type=content_type)
        
        # Filter items that need processing
        if not force_reprocess:
            # Only process items without cleaned text or very short text (likely needs reprocessing)
            queryset = queryset.filter(
                models.Q(book_content__isnull=True) |
                models.Q(book_content='') |
                models.Q(book_content__length__lt=50)  # Very short text likely needs reprocessing
            )
        
        total_items = queryset.count()
        logger.info(f"Found {total_items} items to process")
        
        if dry_run:
            return {
                'items_found': total_items,
                'dry_run': True,
                'message': f'Would process {total_items} items'
            }
        
        # Process in batches for memory efficiency
        processed_items = 0
        all_results = []
        
        # Use iterator() to avoid loading all items into memory at once
        for batch_start in range(0, total_items, self.batch_size):
            batch_items = list(
                queryset[batch_start:batch_start + self.batch_size].select_for_update()
            )
            
            if not batch_items:
                break
            
            batch_results = self.process_content_batch(batch_items)
            all_results.extend(batch_results)
            processed_items += len(batch_items)
            
            # Log progress
            progress = (processed_items / total_items) * 100
            logger.info(f"Progress: {processed_items}/{total_items} ({progress:.1f}%)")
            
            # Force garbage collection after each batch
            gc.collect()
        
        total_time = time.time() - start_time
        
        # Calculate final statistics
        successful_items = sum(1 for r in all_results if r['success'])
        failed_items = len(all_results) - successful_items
        
        summary = {
            'total_items_found': total_items,
            'items_processed': len(all_results),
            'successful_items': successful_items,
            'failed_items': failed_items,
            'total_chars_processed': self.stats['total_chars_processed'],
            'total_processing_time': total_time,
            'average_time_per_item': total_time / len(all_results) if all_results else 0,
            'chars_per_second': self.stats['total_chars_processed'] / total_time if total_time > 0 else 0,
            'errors': self.stats['errors']
        }
        
        logger.info(
            f"Batch processing complete: "
            f"{successful_items}/{total_items} items processed successfully "
            f"in {total_time:.2f}s ({summary['chars_per_second']:.0f} chars/sec)"
        )
        
        return summary
    
    def reindex_search_vectors(self, content_type: str = 'pdf') -> Dict[str, any]:
        """
        Rebuild search vectors for all content items (PostgreSQL only).
        
        Args:
            content_type: Type of content to reindex
            
        Returns:
            Reindexing summary
        """
        if 'postgresql' not in settings.DATABASES['default']['ENGINE']:
            logger.warning("Search vector reindexing only available with PostgreSQL")
            return {'error': 'PostgreSQL required for search vector operations'}
        
        start_time = time.time()
        
        # Get items with content but without current search vectors
        queryset = ContentItem.objects.filter(
            is_active=True,
            content_type=content_type,
            book_content__isnull=False
        ).exclude(book_content='')
        
        total_items = queryset.count()
        logger.info(f"Reindexing search vectors for {total_items} {content_type} items")
        
        updated_count = 0
        
        # Process in batches
        for batch_start in range(0, total_items, self.batch_size):
            batch_items = queryset[batch_start:batch_start + self.batch_size]
            
            with transaction.atomic():
                for item in batch_items:
                    try:
                        item.update_search_vector()
                        item.save(update_fields=['search_vector'])
                        updated_count += 1
                    except Exception as e:
                        logger.error(f"Error updating search vector for {item.id}: {e}")
            
            # Log progress
            progress = (batch_start + len(batch_items)) / total_items * 100
            logger.info(f"Reindexing progress: {progress:.1f}%")
        
        total_time = time.time() - start_time
        
        return {
            'items_processed': total_items,
            'items_updated': updated_count,
            'processing_time': total_time,
            'items_per_second': updated_count / total_time if total_time > 0 else 0
        }


class DatabaseOptimizer:
    """
    Utilities for optimizing database performance for Arabic text search.
    """
    
    @staticmethod
    def create_trigram_indexes():
        """
        Create trigram indexes for fuzzy Arabic text matching (PostgreSQL only).
        """
        if 'postgresql' not in settings.DATABASES['default']['ENGINE']:
            logger.warning("Trigram indexes only available with PostgreSQL")
            return False
        
        try:
            with connection.cursor() as cursor:
                # Enable pg_trgm extension
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
                
                # Create trigram indexes for Arabic text search
                indexes = [
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_title_ar_trgm ON media_manager_contentitem USING gin (title_ar gin_trgm_ops);",
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_description_ar_trgm ON media_manager_contentitem USING gin (description_ar gin_trgm_ops);",
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_book_content_trgm ON media_manager_contentitem USING gin (book_content gin_trgm_ops);",
                ]
                
                for sql in indexes:
                    logger.info(f"Creating index: {sql}")
                    cursor.execute(sql)
                    
            logger.info("Trigram indexes created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error creating trigram indexes: {e}")
            return False
    
    @staticmethod
    def analyze_arabic_text_performance():
        """
        Analyze performance characteristics of Arabic text in the database.
        """
        try:
            with connection.cursor() as cursor:
                # Get statistics about text content
                stats_queries = [
                    ("Total PDF items with book content", 
                     "SELECT COUNT(*) FROM media_manager_contentitem WHERE content_type='pdf' AND book_content IS NOT NULL AND book_content != '';"),
                    
                    ("Average book content length",
                     "SELECT AVG(LENGTH(book_content)) FROM media_manager_contentitem WHERE content_type='pdf' AND book_content IS NOT NULL;"),
                     
                    ("Total characters in all books",
                     "SELECT SUM(LENGTH(book_content)) FROM media_manager_contentitem WHERE content_type='pdf' AND book_content IS NOT NULL;"),
                     
                    ("Books with Arabic content (heuristic)",
                     "SELECT COUNT(*) FROM media_manager_contentitem WHERE book_content ~ '[\\u0600-\\u06FF]+';"),
                ]
                
                results = {}
                for description, query in stats_queries:
                    cursor.execute(query)
                    result = cursor.fetchone()[0]
                    results[description] = result
                    logger.info(f"{description}: {result}")
                
                return results
                
        except Exception as e:
            logger.error(f"Error analyzing text performance: {e}")
            return {}


# === UTILITY FUNCTIONS ===

def get_content_processor(batch_size: int = 100) -> ContentTextProcessor:
    """
    Factory function to create optimally configured content processor.
    
    Args:
        batch_size: Database batch size for processing
        
    Returns:
        Configured ContentTextProcessor instance
    """
    return ContentTextProcessor(batch_size=batch_size)


def quick_clean_and_search(text: str) -> Tuple[str, str]:
    """
    Quick cleaning function for immediate use in views/services.
    
    Args:
        text: Raw text to clean
        
    Returns:
        Tuple of (cleaned_text, search_ready_text)
    """
    processor = ArabicTextProcessor(max_workers=1)
    result = processor.process_single_document(text)
    return result['cleaned_text'], result['search_text']


def estimate_processing_time(total_chars: int, chars_per_second: float = 50000) -> float:
    """
    Estimate processing time for a given amount of text.
    
    Args:
        total_chars: Total characters to process
        chars_per_second: Processing rate (default based on benchmarks)
        
    Returns:
        Estimated time in seconds
    """
    return total_chars / chars_per_second