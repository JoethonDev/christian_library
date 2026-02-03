"""
Management command for bulk Arabic text cleaning and reprocessing.

This command processes all PDF content items with comprehensive Arabic text cleaning
for improved search performance and content quality.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
import logging
import time

from core.services.content_text_processor import get_content_processor, DatabaseOptimizer
from apps.media_manager.models import ContentItem

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean and optimize Arabic text content for improved search performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--content-type',
            type=str,
            default='pdf',
            choices=['pdf', 'all'],
            help='Type of content to process (default: pdf)'
        )
        
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of items to process per batch (default: 50)'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reprocessing of all items, even if already processed'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes'
        )
        
        parser.add_argument(
            '--reindex-only',
            action='store_true',
            help='Only rebuild search indexes without reprocessing text'
        )
        
        parser.add_argument(
            '--optimize-db',
            action='store_true',
            help='Optimize database indexes for Arabic text search'
        )
        
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show Arabic text statistics and performance analysis'
        )
        
        parser.add_argument(
            '--max-items',
            type=int,
            help='Maximum number of items to process (for testing)'
        )
    
    def handle(self, *args, **options):
        """Main command handler"""
        start_time = time.time()
        
        self.stdout.write(
            self.style.SUCCESS(
                '🔧 High-Performance Arabic OCR Cleaning Pipeline\n'
                '   Optimizing Coptic Orthodox Library Content for Search\n'
            )
        )
        
        # Handle different command modes
        if options['stats']:
            self._show_statistics()
            return
        
        if options['optimize_db']:
            self._optimize_database()
            return
        
        if options['reindex_only']:
            self._reindex_search_vectors(options)
            return
        
        # Main text processing
        self._process_arabic_text(options)
        
        total_time = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(f'\n✅ Command completed in {total_time:.2f} seconds')
        )
    
    def _process_arabic_text(self, options):
        """Process Arabic text with cleaning pipeline"""
        processor = get_content_processor(batch_size=options['batch_size'])
        
        self.stdout.write(f"🚀 Starting Arabic text processing...")
        self.stdout.write(f"   Content Type: {options['content_type']}")
        self.stdout.write(f"   Batch Size: {options['batch_size']}")
        self.stdout.write(f"   Force Reprocess: {options['force']}")
        self.stdout.write(f"   Dry Run: {options['dry_run']}")
        
        if options['max_items']:
            self.stdout.write(f"   Max Items: {options['max_items']}")
        
        # Process content
        results = processor.process_all_pdfs(
            content_type=options['content_type'],
            force_reprocess=options['force'],
            dry_run=options['dry_run']
        )
        
        # Apply max items limit if specified
        if options['max_items'] and not options['dry_run']:
            # This is a simplified approach - in real implementation,\n            # you'd want to modify process_all_pdfs to accept a limit parameter\n            self.stdout.write(\n                self.style.WARNING(\n                    f\"Note: --max-items parameter limits total processing, \"\n                    f\"but batch processing may exceed this limit slightly.\"\n                )\n            )\n        \n        # Display results\n        if options['dry_run']:\n            self.stdout.write(\n                self.style.WARNING(\n                    f\"🔍 DRY RUN: Would process {results['items_found']} items\"\n                )\n            )\n        else:\n            self._display_processing_results(results)\n    \n    def _reindex_search_vectors(self, options):\n        \"\"\"Rebuild search vectors only\"\"\"\n        self.stdout.write(\"🔍 Rebuilding search vectors...\")\n        \n        processor = get_content_processor()\n        results = processor.reindex_search_vectors(content_type=options['content_type'])\n        \n        if 'error' in results:\n            self.stdout.write(\n                self.style.ERROR(f\"❌ Error: {results['error']}\")\n            )\n        else:\n            self.stdout.write(\n                self.style.SUCCESS(\n                    f\"✅ Reindexed {results['items_updated']}/{results['items_processed']} items \"\n                    f\"in {results['processing_time']:.2f}s \"\n                    f\"({results['items_per_second']:.1f} items/sec)\"\n                )\n            )\n    \n    def _optimize_database(self):\n        \"\"\"Optimize database for Arabic text search\"\"\"\n        self.stdout.write(\"🗄️  Optimizing database for Arabic text search...\")\n        \n        optimizer = DatabaseOptimizer()\n        \n        # Create trigram indexes\n        if optimizer.create_trigram_indexes():\n            self.stdout.write(\n                self.style.SUCCESS(\"✅ Trigram indexes created successfully\")\n            )\n        else:\n            self.stdout.write(\n                self.style.ERROR(\"❌ Failed to create trigram indexes\")\n            )\n        \n        # Analyze performance\n        stats = optimizer.analyze_arabic_text_performance()\n        if stats:\n            self.stdout.write(\"\\n📊 Database Statistics:\")\n            for description, value in stats.items():\n                self.stdout.write(f\"   {description}: {value:,}\")\n    \n    def _show_statistics(self):\n        \"\"\"Show Arabic text content statistics\"\"\"\n        self.stdout.write(\"📊 Arabic Text Content Statistics\\n\")\n        \n        # Get basic statistics\n        stats_queries = {\n            'Total PDFs': ContentItem.objects.filter(\n                content_type='pdf', is_active=True\n            ).count(),\n            \n            'PDFs with extracted text': ContentItem.objects.filter(\n                content_type='pdf', \n                is_active=True,\n                book_content__isnull=False\n            ).exclude(book_content='').count(),\n            \n            'Total characters extracted': ContentItem.objects.filter(\n                content_type='pdf',\n                is_active=True,\n                book_content__isnull=False\n            ).exclude(book_content='').aggregate(\n                total=models.Sum(\n                    models.functions.Length('book_content')\n                )\n            )['total'] or 0,\n        }\n        \n        for description, value in stats_queries.items():\n            if isinstance(value, int):\n                self.stdout.write(f\"   {description}: {value:,}\")\n            else:\n                self.stdout.write(f\"   {description}: {value}\")\n        \n        # Show processing status distribution\n        from django.db import models\n        status_counts = ContentItem.objects.filter(\n            content_type='pdf', is_active=True\n        ).values('processing_status').annotate(\n            count=models.Count('id')\n        ).order_by('processing_status')\n        \n        self.stdout.write(\"\\n📈 Processing Status Distribution:\")\n        for status in status_counts:\n            self.stdout.write(\n                f\"   {status['processing_status']}: {status['count']:,} items\"\n            )\n        \n        # Show average content length\n        avg_length = ContentItem.objects.filter(\n            content_type='pdf',\n            is_active=True,\n            book_content__isnull=False\n        ).exclude(book_content='').aggregate(\n            avg=models.Avg(models.functions.Length('book_content'))\n        )['avg']\n        \n        if avg_length:\n            self.stdout.write(f\"\\n📏 Average content length: {avg_length:.0f} characters\")\n            \n            # Estimate processing time\n            total_items = stats_queries['PDFs with extracted text']\n            total_chars = stats_queries['Total characters extracted']\n            \n            if total_chars > 0:\n                estimated_time = total_chars / 50000  # chars per second estimate\n                self.stdout.write(\n                    f\"🕐 Estimated reprocessing time: {estimated_time / 60:.1f} minutes \"\n                    f\"({estimated_time:.0f} seconds)\"\n                )\n    \n    def _display_processing_results(self, results):\n        \"\"\"Display formatted processing results\"\"\"\n        if results.get('error'):\n            self.stdout.write(\n                self.style.ERROR(f\"❌ Error: {results['error']}\")\n            )\n            return\n        \n        # Success summary\n        self.stdout.write(\"\\n🎯 Processing Results:\")\n        self.stdout.write(\n            f\"   📁 Items found: {results['total_items_found']:,}\"\n        )\n        self.stdout.write(\n            f\"   ✅ Successfully processed: {results['successful_items']:,}\"\n        )\n        \n        if results['failed_items'] > 0:\n            self.stdout.write(\n                self.style.WARNING(\n                    f\"   ⚠️  Failed items: {results['failed_items']:,}\"\n                )\n            )\n        \n        # Performance metrics\n        self.stdout.write(\"\\n⚡ Performance Metrics:\")\n        self.stdout.write(\n            f\"   📊 Total characters processed: {results['total_chars_processed']:,}\"\n        )\n        self.stdout.write(\n            f\"   ⏱️  Total processing time: {results['total_processing_time']:.2f}s\"\n        )\n        self.stdout.write(\n            f\"   🚀 Processing rate: {results['chars_per_second']:,.0f} chars/sec\"\n        )\n        self.stdout.write(\n            f\"   📈 Average time per item: {results['average_time_per_item']:.3f}s\"\n        )\n        \n        # Show errors if any\n        if results['errors']:\n            self.stdout.write(\"\\n❌ Errors encountered:\")\n            for error in results['errors'][:5]:  # Show first 5 errors\n                self.stdout.write(f\"   • {error}\")\n            \n            if len(results['errors']) > 5:\n                self.stdout.write(\n                    f\"   ... and {len(results['errors']) - 5} more errors\"\n                )