# Management command for bulk SEO metadata generation
# File: apps/media_manager/management/commands/generate_seo_metadata.py

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db import models
from apps.media_manager.models import ContentItem
from apps.media_manager.tasks import bulk_generate_seo_metadata
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate SEO metadata for content items using Gemini AI'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--content-type',
            choices=['video', 'audio', 'pdf'],
            help='Generate SEO for specific content type only'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of items to process'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate SEO for items that already have it'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually doing it'
        )
        parser.add_argument(
            '--priority',
            choices=['high', 'medium', 'low'],
            help='Process items by priority (high = no SEO, medium = partial SEO, low = complete SEO)'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='use_async',
            help='Use Celery tasks (recommended for large batches)'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🔍 SEO Metadata Generation Tool')
        )
        
        # Build queryset
        queryset = ContentItem.objects.filter(is_active=True)
        
        if options['content_type']:
            queryset = queryset.filter(content_type=options['content_type'])
        
        # Priority filtering
        if options['priority'] == 'high':
            # Items with no SEO metadata
            queryset = queryset.filter(
                seo_keywords_ar__len=0,
                seo_keywords_en__len=0
            )
        elif options['priority'] == 'medium':
            # Items with partial SEO metadata
            queryset = queryset.filter(
                models.Q(seo_keywords_ar__len=0) | models.Q(seo_keywords_en__len=0) |
                models.Q(seo_meta_description_ar='') | models.Q(seo_meta_description_en='')
            ).exclude(
                seo_keywords_ar__len=0,
                seo_keywords_en__len=0
            )
        elif options['priority'] == 'low':
            # Items with complete SEO metadata (for regeneration)
            queryset = queryset.filter(
                seo_keywords_ar__len__gt=0,
                seo_keywords_en__len__gt=0
            ).exclude(
                seo_meta_description_ar='',
                seo_meta_description_en=''
            )
        
        # Force regeneration filter
        if not options['force']:
            queryset = queryset.filter(
                models.Q(seo_keywords_ar__len=0) | models.Q(seo_keywords_en__len=0)
            )
        
        # Apply limit
        if options['limit']:
            queryset = queryset[:options['limit']]
        
        # Get items with media files
        items_to_process = []
        total_items = queryset.count()
        
        self.stdout.write(f'📊 Found {total_items} content items to analyze...')
        
        for item in queryset.select_related('videometa', 'audiometa', 'pdfmeta'):
            # Check if media file exists
            meta = item.get_meta_object()
            if meta and hasattr(meta, 'original_file') and meta.original_file:
                try:
                    # Check if file exists on disk
                    file_path = meta.original_file.path
                    import os
                    if os.path.exists(file_path):
                        items_to_process.append(item)
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'⚠️  File missing: {item.get_title()} ({file_path})')
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️  Error checking file for {item.get_title()}: {e}')
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  No media file: {item.get_title()}')
                )
        
        processable_count = len(items_to_process)
        self.stdout.write(f'✅ {processable_count} items have valid media files')
        
        if processable_count == 0:
            self.stdout.write(self.style.WARNING('No items to process. Exiting.'))
            return
        
        # Show summary
        content_type_summary = {}
        seo_status_summary = {'no_seo': 0, 'partial_seo': 0, 'complete_seo': 0}
        
        for item in items_to_process:
            # Content type count
            content_type_summary[item.content_type] = content_type_summary.get(item.content_type, 0) + 1
            
            # SEO status
            has_ar_keywords = len(item.seo_keywords_ar) > 0
            has_en_keywords = len(item.seo_keywords_en) > 0
            has_ar_meta = bool(item.seo_meta_description_ar)
            has_en_meta = bool(item.seo_meta_description_en)
            
            if not (has_ar_keywords or has_en_keywords):
                seo_status_summary['no_seo'] += 1
            elif has_ar_keywords and has_en_keywords and has_ar_meta and has_en_meta:
                seo_status_summary['complete_seo'] += 1
            else:
                seo_status_summary['partial_seo'] += 1
        
        # Display summary
        self.stdout.write('\n📋 Processing Summary:')
        self.stdout.write('─' * 40)
        
        for content_type, count in content_type_summary.items():
            self.stdout.write(f'  {content_type.upper()}: {count} items')
        
        self.stdout.write(f'\n📊 SEO Status:')
        self.stdout.write(f'  🔴 No SEO: {seo_status_summary["no_seo"]} items')
        self.stdout.write(f'  🟡 Partial SEO: {seo_status_summary["partial_seo"]} items')
        self.stdout.write(f'  🟢 Complete SEO: {seo_status_summary["complete_seo"]} items')
        
        if options['dry_run']:
            self.stdout.write('\n🔍 DRY RUN - No changes will be made')
            
            # Show first 10 items that would be processed
            self.stdout.write('\n📝 Items that would be processed:')
            for i, item in enumerate(items_to_process[:10]):
                status = '🔴' if not (item.seo_keywords_ar and item.seo_keywords_en) else \
                        '🟡' if not (item.seo_meta_description_ar and item.seo_meta_description_en) else '🟢'
                self.stdout.write(f'  {i+1:2d}. {status} {item.get_title()} ({item.content_type})')
            
            if len(items_to_process) > 10:
                self.stdout.write(f'  ... and {len(items_to_process) - 10} more items')
            
            return
        
        # Confirm processing
        self.stdout.write(f'\n🚀 Ready to process {processable_count} items')
        
        if not options['use_async']:
            self.stdout.write(
                self.style.WARNING('⚠️  Synchronous processing may take a long time!')
            )
            self.stdout.write(
                self.style.WARNING('⚠️  Consider using --async for better performance')
            )
        
        if not options.get('verbosity', 1) >= 2:
            confirm = input('\nProceed? [y/N]: ')
            if confirm.lower() != 'y':
                self.stdout.write('Cancelled.')
                return
        
        # Process items
        if options['use_async']:
            # Use Celery for async processing
            self.stdout.write('🔄 Queueing items for async processing...')
            
            count = bulk_generate_seo_metadata(
                content_type=options['content_type'],
                limit=options['limit']
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'✅ Queued {count} items for SEO generation')
            )
            self.stdout.write('📱 Monitor progress in Celery logs or admin dashboard')
            
        else:
            # Process synchronously
            self.stdout.write('🔄 Processing items synchronously...')
            
            success_count = 0
            error_count = 0
            
            for i, item in enumerate(items_to_process, 1):
                try:
                    self.stdout.write(f'  {i:3d}/{processable_count} Processing: {item.get_title()[:50]}...', ending='')
                    
                    # Get media file path
                    meta = item.get_meta_object()
                    file_path = meta.original_file.path
                    
                    # Generate SEO metadata
                    from apps.media_manager.services.gemini_service import get_gemini_service
                    service = get_gemini_service()
                    
                    if not service.is_available():
                        raise Exception("Gemini AI service not available")
                    
                    success, seo_metadata = service.generate_seo_metadata(file_path, item.content_type)
                    
                    if success and seo_metadata:
                        # Update the item
                        item.update_seo_from_gemini(seo_metadata)
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(' ✅'))
                        
                        if options['verbosity'] >= 2:
                            keyword_count = len(seo_metadata.get('seo_keywords_ar', [])) + len(seo_metadata.get('seo_keywords_en', []))
                            self.stdout.write(f'     Generated {keyword_count} keywords')
                    else:
                        error_msg = seo_metadata.get('error', 'Unknown error') if isinstance(seo_metadata, dict) else 'Generation failed'
                        raise Exception(error_msg)
                    
                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f' ❌ {str(e)}'))
                    
                    if options['verbosity'] >= 2:
                        logger.exception(f"Error processing {item.id}")
            
            # Final summary
            self.stdout.write('\n' + '=' * 50)
            self.stdout.write(
                self.style.SUCCESS(f'✅ SEO Generation Complete!')
            )
            self.stdout.write(f'📊 Results:')
            self.stdout.write(f'  ✅ Successful: {success_count}')
            self.stdout.write(f'  ❌ Failed: {error_count}')
            self.stdout.write(f'  📈 Success Rate: {(success_count/processable_count*100):.1f}%')
            
            if error_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Check logs for error details')
                )
        
        self.stdout.write('\n🎉 SEO metadata generation completed!')
        self.stdout.write('📱 View results in the SEO Dashboard: /admin/seo/')