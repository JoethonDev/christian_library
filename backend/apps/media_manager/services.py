"""
Media Management Service Layer
Handles all business logic for content upload, processing, and management
"""
import os
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _
from django.db import transaction

from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag


class MediaProcessingService:
    """Service for media file processing and management"""
    
    def __init__(self):
        self.media_root = settings.MEDIA_ROOT
        self.max_audio_size = 50 * 1024 * 1024  # 50MB
        
    def upload_video(self, file: UploadedFile, title_ar: str, title_en: str = "",
                    description_ar: str = "", description_en: str = "",
                    tags: List[str] = None) -> Tuple[bool, str, ContentItem]:
        """
        Upload and process video file
        Returns: (success, message, content_item)
        """
        try:
            with transaction.atomic():
                # Create content item
                content_item = ContentItem.objects.create(
                    title_ar=title_ar,
                    title_en=title_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    content_type='video'
                )
                
                # Save original file
                original_path = f'original/videos/{content_item.id}_{file.name}'
                video_meta = VideoMeta.objects.create(
                    content_item=content_item,
                    processing_status='uploading'
                )
                
                # Save file to filesystem
                full_path = os.path.join(self.media_root, original_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)
                
                video_meta.original_file = original_path
                video_meta.save()
                
                # Process tags
                if tags:
                    self._process_tags(content_item, tags)
                
                # Queue for HLS processing
                self._queue_video_processing(video_meta)
                
                return True, _("Video uploaded successfully and queued for processing"), content_item
                
        except Exception as e:
            return False, f"{_('Error uploading video')}: {str(e)}", None
    
    def upload_audio(self, file: UploadedFile, title_ar: str, title_en: str = "",
                    description_ar: str = "", description_en: str = "",
                    module_id: str = None, tags: List[str] = None) -> Tuple[bool, str, ContentItem]:
        """
        Upload and process audio file
        Returns: (success, message, content_item)
        """
        try:
            with transaction.atomic():
                # Create content item
                module = Module.objects.get(id=module_id) if module_id else None
                content_item = ContentItem.objects.create(
                    title_ar=title_ar,
                    title_en=title_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    content_type='audio',
                    module=module
                )
                
                # Process and compress audio
                compressed_path = self._compress_audio(file, content_item.id)
                
                # Get audio metadata
                duration, bitrate = self._get_audio_metadata(compressed_path)
                
                audio_meta = AudioMeta.objects.create(
                    content_item=content_item,
                    original_file=compressed_path,
                    duration_seconds=duration,
                    bitrate=bitrate,
                    file_size=os.path.getsize(os.path.join(self.media_root, compressed_path))
                )
                
                # Process tags
                if tags:
                    self._process_tags(content_item, tags)
                
                return True, _("Audio uploaded and compressed successfully"), content_item
                
        except Exception as e:
            return False, f"{_('Error uploading audio')}: {str(e)}", None
    
    def upload_pdf(self, file: UploadedFile, title_ar: str, title_en: str = "",
                  description_ar: str = "", description_en: str = "",
                  module_id: str = None, tags: List[str] = None) -> Tuple[bool, str, ContentItem]:
        """
        Upload and process PDF file
        Returns: (success, message, content_item)
        """
        try:
            with transaction.atomic():
                # Create content item
                module = Module.objects.get(id=module_id) if module_id else None
                content_item = ContentItem.objects.create(
                    title_ar=title_ar,
                    title_en=title_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    content_type='pdf',
                    module=module
                )
                
                # Compress PDF
                compressed_path = self._compress_pdf(file, content_item.id)
                
                # Get PDF metadata
                pages = self._get_pdf_pages(compressed_path)
                
                pdf_meta = PdfMeta.objects.create(
                    content_item=content_item,
                    original_file=compressed_path,
                    pages=pages,
                    file_size=os.path.getsize(os.path.join(self.media_root, compressed_path))
                )
                
                # Process tags
                if tags:
                    self._process_tags(content_item, tags)
                
                return True, _("PDF uploaded and compressed successfully"), content_item
                
        except Exception as e:
            return False, f"{_('Error uploading PDF')}: {str(e)}", None
    
    def delete_content(self, content_item: ContentItem) -> Tuple[bool, str]:
        """
        Safely delete content item and all associated files
        Returns: (success, message)
        """
        try:
            with transaction.atomic():
                # Get file paths to delete
                files_to_delete = []
                
                if content_item.content_type == 'video':
                    video_meta = getattr(content_item, 'videometa', None)
                    if video_meta:
                        if video_meta.original_file:
                            files_to_delete.append(video_meta.original_file.path)
                        if video_meta.hls_720p_path:
                            files_to_delete.append(os.path.join(self.media_root, video_meta.hls_720p_path))
                        if video_meta.hls_480p_path:
                            files_to_delete.append(os.path.join(self.media_root, video_meta.hls_480p_path))
                            
                elif content_item.content_type == 'audio':
                    audio_meta = getattr(content_item, 'audiometa', None)
                    if audio_meta and audio_meta.original_file:
                        files_to_delete.append(audio_meta.original_file.path)
                        
                elif content_item.content_type == 'pdf':
                    pdf_meta = getattr(content_item, 'pdfmeta', None)
                    if pdf_meta and pdf_meta.original_file:
                        files_to_delete.append(pdf_meta.original_file.path)
                
                # Delete database records
                content_item.delete()
                
                # Delete files from filesystem
                for file_path in files_to_delete:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                
                return True, _("Content deleted successfully")
                
        except Exception as e:
            return False, f"{_('Error deleting content')}: {str(e)}"
    
    def _compress_audio(self, file: UploadedFile, content_id: uuid.UUID) -> str:
        """Compress audio to 192kbps max 50MB"""
        output_path = f'compressed/audio/{content_id}.mp3'
        full_output_path = os.path.join(self.media_root, output_path)
        os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
        
        # Save temp file first
        temp_path = f'/tmp/{uuid.uuid4()}_{file.name}'
        with open(temp_path, 'wb+') as temp_file:
            for chunk in file.chunks():
                temp_file.write(chunk)
        
        try:
            # Use FFmpeg for compression
            cmd = [
                'ffmpeg', '-i', temp_path,
                '-acodec', 'libmp3lame',
                '-b:a', '192k',
                '-ac', '2',  # Stereo
                '-ar', '44100',  # Sample rate
                '-y',  # Overwrite
                full_output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Check file size and reduce quality if needed
            while os.path.getsize(full_output_path) > self.max_audio_size:
                # Reduce bitrate
                cmd[6] = '128k'
                subprocess.run(cmd, check=True, capture_output=True)
                if os.path.getsize(full_output_path) <= self.max_audio_size:
                    break
                cmd[6] = '96k'
                subprocess.run(cmd, check=True, capture_output=True)
                break
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
        return output_path
    
    def _compress_pdf(self, file: UploadedFile, content_id: uuid.UUID) -> str:
        """Compress PDF using Ghostscript"""
        output_path = f'compressed/pdf/{content_id}.pdf'
        full_output_path = os.path.join(self.media_root, output_path)
        os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
        
        # Save temp file first
        temp_path = f'/tmp/{uuid.uuid4()}_{file.name}'
        with open(temp_path, 'wb+') as temp_file:
            for chunk in file.chunks():
                temp_file.write(chunk)
        
        try:
            # Use Ghostscript for compression
            cmd = [
                'gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
                '-dPDFSETTINGS=/ebook', '-dNOPAUSE', '-dQUIET', '-dBATCH',
                f'-sOutputFile={full_output_path}', temp_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
        return output_path
    
    def _queue_video_processing(self, video_meta: VideoMeta):
        """Queue video for HLS processing"""
        # This would typically use Celery or similar
        # For now, mark as queued
        video_meta.processing_status = 'queued'
        video_meta.save()
    
    def _get_audio_metadata(self, file_path: str) -> Tuple[int, int]:
        """Get audio duration and bitrate using FFmpeg"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            import json
            data = json.loads(result.stdout)
            
            duration = int(float(data['format']['duration']))
            bitrate = int(data['format']['bit_rate']) // 1000  # Convert to kbps
            
            return duration, bitrate
        except:
            return 0, 192  # Default values
    
    def _get_pdf_pages(self, file_path: str) -> int:
        """Get number of PDF pages"""
        try:
            cmd = ['pdfinfo', file_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'Pages:' in line:
                    return int(line.split(':')[1].strip())
            return 1
        except:
            return 1
    
    def _process_tags(self, content_item: ContentItem, tag_names: List[str]):
        """Process and assign tags to content item"""
        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if tag_name:
                tag, created = Tag.objects.get_or_create(
                    name_ar=tag_name,
                    defaults={'name_en': tag_name}
                )
                content_item.tags.add(tag)


class ContentManagementService:
    """Service for content management operations"""
    
    def get_content_list(self, content_type: str = None, search_query: str = "",
                        page: int = 1, per_page: int = 20) -> Dict:
        """Get paginated content list with filtering"""
        from django.core.paginator import Paginator
        from django.db.models import Q
        
        queryset = ContentItem.objects.select_related('module__course').prefetch_related('tags')
        
        # Filter by content type
        if content_type and content_type in ['video', 'audio', 'pdf']:
            queryset = queryset.filter(content_type=content_type)
        
        # Search filter
        if search_query:
            queryset = queryset.filter(
                Q(title_ar__icontains=search_query) |
                Q(title_en__icontains=search_query) |
                Q(description_ar__icontains=search_query) |
                Q(description_en__icontains=search_query)
            )
        
        # Order by creation date
        queryset = queryset.order_by('-created_at')
        
        # Pagination
        paginator = Paginator(queryset, per_page)
        page_obj = paginator.get_page(page)
        
        return {
            'items': page_obj,
            'total_count': paginator.count,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page,
            'total_pages': paginator.num_pages
        }
    
    def get_content_stats(self) -> Dict:
        """Get content statistics for dashboard"""
        return {
            'total_videos': ContentItem.objects.filter(content_type='video', is_active=True).count(),
            'total_audios': ContentItem.objects.filter(content_type='audio', is_active=True).count(),
            'total_pdfs': ContentItem.objects.filter(content_type='pdf', is_active=True).count(),
            'total_all': ContentItem.objects.filter(is_active=True).count(),
        }