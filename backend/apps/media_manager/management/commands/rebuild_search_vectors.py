"""
Management command to rebuild search vectors for all ContentItem instances.
This should be run after updating search vector weights or configurations.

Usage:
    python manage.py rebuild_search_vectors
    python manage.py rebuild_search_vectors --batch-size=100
"""

from django.core.management.base import BaseCommand
from django.db import connection
from apps.media_manager.models import ContentItem
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Rebuild search vectors for all ContentItem instances with updated weights'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of items to process in each batch (default: 50)'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        
        # Check if we're using PostgreSQL
        if 'postgresql' not in connection.settings_dict['ENGINE']:
            self.stdout.write(
                self.style.WARNING('⚠️  Search vectors are only supported with PostgreSQL. Skipping.')
            )
            return

        self.stdout.write(self.style.SUCCESS('🔍 Starting search vector rebuild...'))
        
        # Get total count
        total = ContentItem.objects.count()
        self.stdout.write(f'📊 Total content items: {total}')
        
        if total == 0:
            self.stdout.write(self.style.WARNING('No content items found.'))
            return
        
        # Process in batches
        processed = 0
        updated = 0
        skipped = 0
        
        for i in range(0, total, batch_size):
            batch = ContentItem.objects.all()[i:i+batch_size]
            
            for item in batch:
                try:
                    item.update_search_vector()
                    item.save(update_fields=['search_vector'])
                    updated += 1
                    processed += 1
                except Exception as e:
                    logger.error(f"Error updating search vector for {item.id}: {e}")
                    skipped += 1
                    processed += 1
            
            # Progress update
            self.stdout.write(
                f'✅ Processed {processed}/{total} items... ({updated} updated, {skipped} skipped)',
                ending='\r'
            )
        
        self.stdout.write('')  # New line after progress updates
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Search vector rebuild complete!\n'
                f'   Updated: {updated}\n'
                f'   Skipped: {skipped}\n'
                f'   Total:   {processed}'
            )
        )
