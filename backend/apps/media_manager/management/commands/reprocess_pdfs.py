"""
Management command for reprocessing existing PDFs with the new Arabic cleaning pipeline.

This command re-extracts text from PDFs and applies the enhanced Arabic cleaning
for better search performance.
"""

from django.core.management.base import BaseCommand
from django.db import transaction, models
from django.utils import timezone
import logging
import time

from apps.media_manager.models import ContentItem
from apps.media_manager.tasks import extract_and_index_contentitem

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocess existing PDF content with enhanced Arabic text extraction and cleaning'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Number of items to process concurrently (default: 10)'
        )
        
        parser.add_argument(
            '--force-all',
            action='store_true',
            help='Reprocess all PDFs, even if already processed'
        )
        
        parser.add_argument(
            '--content-id',
            type=str,
            help='Process specific content item by ID'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes'
        )
        
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Process synchronously instead of using Celery tasks'
        )
    
    def handle(self, *args, **options):
        """Main command handler"""
        start_time = time.time()
        
        self.stdout.write(
            self.style.SUCCESS(
                '🔄 PDF Text Reprocessing with Enhanced Arabic Cleaning\n'
            )
        )
        
        if options['content_id']:
            self._process_single_item(options['content_id'], options)
        else:
            self._process_batch(options)
        
        total_time = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(f'\\n✅ Reprocessing completed in {total_time:.2f} seconds')
        )
    
    def _process_single_item(self, content_id, options):
        \"\"\"Process a single content item\"\"\"
        try:
            content_item = ContentItem.objects.get(id=content_id, content_type='pdf')
            self.stdout.write(f\"🔍 Processing single item: {content_item.title_ar[:50]}...\")
            
            if options['dry_run']:
                self.stdout.write(
                    self.style.WARNING(\"🔍 DRY RUN: Would reprocess this item\")
                )
                return
            
            if options['sync']:
                # Process synchronously
                content_item.extract_text_from_pdf()
                content_item.update_search_vector()
                content_item.save(update_fields=['book_content', 'search_vector', 'updated_at'])
                self.stdout.write(self.style.SUCCESS(\"✅ Processed synchronously\"))
            else:\n                # Use Celery task\n                task = extract_and_index_contentitem.delay(str(content_item.id))\n                self.stdout.write(\n                    self.style.SUCCESS(f\"✅ Queued for processing (Task ID: {task.id})\")\n                )\n        \n        except ContentItem.DoesNotExist:\n            self.stdout.write(\n                self.style.ERROR(f\"❌ Content item {content_id} not found or not a PDF\")\n            )\n    \n    def _process_batch(self, options):\n        \"\"\"Process multiple items in batch\"\"\"\n        # Build queryset\n        queryset = ContentItem.objects.filter(\n            content_type='pdf',\n            is_active=True\n        )\n        \n        if not options['force_all']:\n            # Only process items that haven't been processed or have very little content\n            queryset = queryset.filter(\n                models.Q(book_content__isnull=True) |\n                models.Q(book_content='') |\n                models.Q(book_content__length__lt=100)  # Very short content likely needs reprocessing\n            )\n        \n        total_items = queryset.count()\n        \n        self.stdout.write(f\"📊 Found {total_items:,} PDF items to process\")\n        \n        if options['dry_run']:\n            self.stdout.write(\n                self.style.WARNING(\n                    f\"🔍 DRY RUN: Would reprocess {total_items:,} items\"\n                )\n            )\n            return\n        \n        # Process in batches\n        processed = 0\n        batch_size = options['batch_size']\n        \n        for batch_start in range(0, total_items, batch_size):\n            batch_items = queryset[batch_start:batch_start + batch_size]\n            \n            self.stdout.write(\n                f\"🔄 Processing batch {batch_start + 1}-{min(batch_start + batch_size, total_items)} \"\n                f\"of {total_items:,}\"\n            )\n            \n            if options['sync']:\n                # Process synchronously\n                self._process_batch_sync(batch_items)\n            else:\n                # Queue Celery tasks\n                self._process_batch_async(batch_items)\n            \n            processed += len(batch_items)\n            progress = (processed / total_items) * 100\n            self.stdout.write(\n                f\"📈 Progress: {processed:,}/{total_items:,} ({progress:.1f}%)\"\n            )\n    \n    def _process_batch_sync(self, batch_items):\n        \"\"\"Process batch items synchronously\"\"\"\n        for item in batch_items:\n            try:\n                original_length = len(item.book_content or '')\n                \n                # Re-extract and clean text\n                item.extract_text_from_pdf()\n                item.update_search_vector()\n                item.save(update_fields=['book_content', 'search_vector', 'updated_at'])\n                \n                new_length = len(item.book_content or '')\n                \n                self.stdout.write(\n                    f\"   ✅ {item.title_ar[:40]}... \"\n                    f\"({original_length} → {new_length} chars)\"\n                )\n                \n            except Exception as e:\n                self.stdout.write(\n                    self.style.ERROR(\n                        f\"   ❌ Error processing {item.id}: {str(e)}\"\n                    )\n                )\n    \n    def _process_batch_async(self, batch_items):\n        \"\"\"Process batch items using Celery tasks\"\"\"\n        task_ids = []\n        \n        for item in batch_items:\n            try:\n                task = extract_and_index_contentitem.delay(str(item.id))\n                task_ids.append(task.id)\n                \n                self.stdout.write(\n                    f\"   📤 Queued: {item.title_ar[:40]}... (Task: {task.id[:8]}...)\"\n                )\n                \n            except Exception as e:\n                self.stdout.write(\n                    self.style.ERROR(\n                        f\"   ❌ Error queuing {item.id}: {str(e)}\"\n                    )\n                )\n        \n        if task_ids:\n            self.stdout.write(\n                f\"📋 Queued {len(task_ids)} tasks for background processing\"\n            )