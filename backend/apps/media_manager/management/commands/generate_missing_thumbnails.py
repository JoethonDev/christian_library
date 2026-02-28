import os
import tempfile
import logging
from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
from apps.media_manager.models import ContentItem, VideoMeta, PdfMeta
from core.utils.media_processing import VideoProcessor, PDFProcessor, DependencyError
from core.storage_backends import R2Service

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate thumbnails for content items that are missing them'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Force regeneration of thumbnails')
        parser.add_argument('--limit', type=int, help='Limit number of items to process')
        parser.add_argument('--type', choices=['video', 'pdf', 'audio'], help='Filter by content type')

    def handle(self, *args, **options):
        force = options['force']
        limit = options['limit']
        ctype = options['type']
        
        query = ContentItem.objects.all()
        if not force:
            query = query.filter(thumbnail='')
        
        if ctype:
            query = query.filter(content_type=ctype)
        
        if limit:
            query = query[:limit]
            
        items_to_process = list(query)
        self.stdout.write(self.style.SUCCESS(f"Found {len(items_to_process)} items needing thumbnails"))
        
        video_processor = None
        pdf_processor = None
        r2_service = R2Service() if getattr(settings, 'R2_ENABLED', False) else None
        
        processed = 0
        failed = 0
        
        for item in items_to_process:
            self.stdout.write(f"Processing ({item.content_type}): {item.title_ar[:30]}...")
            
            success = False
            temp_thumb_path = None
            
            try:
                if item.content_type == 'video':
                    meta = getattr(item, 'videometa', None)
                    if meta and meta.original_file:
                        if not video_processor:
                            video_processor = VideoProcessor()
                        
                        thumb_filename = f"thumb_{item.id}.jpg"
                        temp_thumb_path = os.path.join(tempfile.gettempdir(), thumb_filename)
                        
                        video_processor.generate_thumbnail(meta.original_file.path, temp_thumb_path)
                        success = os.path.exists(temp_thumb_path) and os.path.getsize(temp_thumb_path) > 0
                
                elif item.content_type == 'pdf':
                    meta = getattr(item, 'pdfmeta', None)
                    if meta and meta.original_file:
                        if not pdf_processor:
                            pdf_processor = PDFProcessor()
                        
                        thumb_filename = f"thumb_{item.id}.jpg"
                        temp_thumb_path = os.path.join(tempfile.gettempdir(), thumb_filename)
                        
                        pdf_processor.generate_thumbnail(meta.original_file.path, temp_thumb_path)
                        success = os.path.exists(temp_thumb_path) and os.path.getsize(temp_thumb_path) > 0
                
                if success and temp_thumb_path:
                    with open(temp_thumb_path, 'rb') as f:
                        item.thumbnail.save(f"thumb_{item.id}.jpg", File(f), save=True)
                    
                    if r2_service:
                        r2_service.upload_thumbnail(item)
                    
                    processed += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Thumbnail generated and saved"))
                else:
                    self.stdout.write(self.style.WARNING(f"  ✗ Could not generate thumbnail (meta missing or file not found)"))
                    failed += 1
                    
            except DependencyError as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Dependency error: {e}"))
                failed += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {e}"))
                failed += 1
            finally:
                if temp_thumb_path and os.path.exists(temp_thumb_path):
                    os.remove(temp_thumb_path)
                    
        self.stdout.write(self.style.SUCCESS(f"Finished. Processed: {processed}, Failed: {failed}"))
