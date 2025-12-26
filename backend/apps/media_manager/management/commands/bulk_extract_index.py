"""
Management command to extract text and update search index for all PDFs.
Usage: python manage.py bulk_extract_index [--force] [--limit N] [--sync]
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.media_manager.models import ContentItem
from apps.media_manager.tasks import extract_and_index_contentitem
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Extract text and update search index for all PDF content items'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-extraction even if content already has extracted text',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit the number of PDFs to process',
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run extraction synchronously instead of queuing Celery tasks',
        )

    def handle(self, *args, **options):
        force = options['force']
        limit = options.get('limit')
        sync = options['sync']

        # Build queryset
        queryset = ContentItem.objects.filter(
            content_type='pdf',
            is_active=True
        ).select_related('pdfmeta')

        if not force:
            # Only process PDFs without extracted content
            queryset = queryset.filter(book_content__isnull=True) | queryset.filter(book_content='')

        if limit:
            queryset = queryset[:limit]

        total_count = queryset.count()

        if total_count == 0:
            self.stdout.write(
                self.style.WARNING('No PDFs found for processing.')
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f'Found {total_count} PDFs to process.')
        )

        processed_count = 0
        failed_count = 0

        for content_item in queryset:
            try:
                self.stdout.write(f'Processing PDF: {content_item.title_ar} ({content_item.id})')
                
                if sync:
                    # Run synchronously
                    content_item.extract_text_from_pdf()
                    content_item.update_search_vector()
                    content_item.save(update_fields=['book_content', 'search_vector'])
                    
                    extracted_length = len(content_item.book_content) if content_item.book_content else 0
                    if extracted_length > 0:
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ Extracted {extracted_length} characters')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING('  ⚠ No text extracted')
                        )
                else:
                    # Queue Celery task
                    extract_and_index_contentitem.delay(str(content_item.id))
                    self.stdout.write('  ✓ Queued for background processing')

                processed_count += 1

            except Exception as e:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Failed: {str(e)}')
                )
                logger.error(f'Failed to process PDF {content_item.id}: {str(e)}', exc_info=True)

        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(
            self.style.SUCCESS(f'Bulk extraction completed:')
        )
        self.stdout.write(f'  • Processed: {processed_count}/{total_count}')
        self.stdout.write(f'  • Failed: {failed_count}')
        
        if not sync:
            self.stdout.write('\nNote: Tasks have been queued for background processing.')
            self.stdout.write('Check Celery worker logs for detailed progress.')
