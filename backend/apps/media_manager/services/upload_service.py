"""
Media Upload Service Layer
Handles file uploads, validation, and processing initiation
"""
import os
import mimetypes
from typing import Dict, Tuple, Optional
from pathlib import Path
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.translation import gettext_lazy as _
import logging

from ..models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from .content_service import ContentService
from core.utils.exceptions import MediaProcessingError, ValidationError
from core.tasks.media_processing import (
    process_video_to_hls,
    process_audio_compression,
    process_pdf_optimization
)

logger = logging.getLogger(__name__)


class MediaUploadService:
    """Service for handling media file uploads and processing"""
    
    # File size limits (in bytes)
    MAX_VIDEO_SIZE = 1024 * 1024 * 1024  # 1GB
    MAX_AUDIO_SIZE = 100 * 1024 * 1024   # 100MB
    MAX_PDF_SIZE = 50 * 1024 * 1024      # 50MB
    
    # Allowed file types
    ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/avi', 'video/mov', 'video/wmv']
    ALLOWED_AUDIO_TYPES = ['audio/mp3', 'audio/wav', 'audio/m4a', 'audio/aac', 'audio/ogg', 'audio/flac', 'audio/wave', 'audio/x-wav', 'audio/mpeg']
    ALLOWED_PDF_TYPES = ['application/pdf']
    
    @staticmethod
    def validate_file(
        file: UploadedFile,
        content_type: str
    ) -> Tuple[bool, str]:
        """
        Validate uploaded file based on content type
        
        Args:
            file: Uploaded file object
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check file size
        max_size = {
            'video': MediaUploadService.MAX_VIDEO_SIZE,
            'audio': MediaUploadService.MAX_AUDIO_SIZE,
            'pdf': MediaUploadService.MAX_PDF_SIZE
        }.get(content_type)
        if file.size > max_size:
            return False, _('File size exceeds maximum allowed size')
        
        # Check MIME type
        mime_type, _ = mimetypes.guess_type(file.name)
        allowed_types = {
            'video': MediaUploadService.ALLOWED_VIDEO_TYPES,
            'audio': MediaUploadService.ALLOWED_AUDIO_TYPES,
            'pdf': MediaUploadService.ALLOWED_PDF_TYPES
        }.get(content_type, [])
        
        if mime_type not in allowed_types:
            return False, _('File type not supported')
        
        # Additional validations
        if content_type == 'pdf':
            # Validate PDF file header
            file.seek(0)
            header = file.read(4)
            file.seek(0)
            if header != b'%PDF':
                return False, _('Invalid PDF file')
        
        return True, ''
    
    @staticmethod
    def upload_video(
        file: UploadedFile,
        title_ar: str,
        title_en: str = "",
        description_ar: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process video file
        
        Args:
            file: Video file to upload
            title_ar: Arabic title
            title_en: English title  
            description_ar: Arabic description
            description_en: English description
            tag_ids: List of tag UUIDs
            
        Returns:
            Tuple of (success, message, content_item)
        """
        try:
            # Validate file
            is_valid, error_msg = MediaUploadService.validate_file(file, 'video')
            if not is_valid:
                return False, error_msg, None
            
            with transaction.atomic():
                # Create content item
                content_item = ContentService.create_content_item(
                    title_ar=title_ar,
                    content_type='video',
                    description_ar=description_ar,
                    title_en=title_en,
                    description_en=description_en,
                    tag_ids=tag_ids
                )
                
                # Save file and get or create video meta
                file_path = MediaUploadService._save_file(
                    file, 'original/videos', content_item.id
                )
                
                # Get the VideoMeta (created by signal) and update it
                video_meta, created = VideoMeta.objects.get_or_create(
                    content_item=content_item,
                    defaults={
                        'original_file': file_path,
                        'file_size_mb': round(file.size / (1024 * 1024), 2),
                        'processing_status': 'pending'
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    video_meta.original_file = file_path
                    video_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    video_meta.processing_status = 'pending'
                    video_meta.save()
                
                # Queue for background processing
                process_video_to_hls.delay(str(video_meta.id))
                
                logger.info(f"Video uploaded successfully: {content_item.id}")
                return True, _("Video uploaded and queued for processing"), content_item
                
        except Exception as e:
            logger.error(f"Error uploading video: {str(e)}")
            return False, f"{_('Error uploading video')}: {str(e)}", None
    
    @staticmethod
    def upload_audio(
        file: UploadedFile,
        title_ar: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process audio file
        
        Args:
            file: Audio file to upload
            title_ar: Arabic title
            description_ar: Arabic description
            title_en: English title
            description_en: English description
            tag_ids: List of tag UUIDs
            
        Returns:
            Tuple of (success, message, content_item)
        """
        try:
            # Validate file
            is_valid, error_msg = MediaUploadService.validate_file(file, 'audio')
            if not is_valid:
                return False, error_msg, None
            with transaction.atomic():
                # Create content item
                content_item = ContentService.create_content_item(
                    title_ar=title_ar,
                    content_type='audio',
                    description_ar=description_ar,
                    title_en=title_en,
                    description_en=description_en,
                    tag_ids=tag_ids
                )
                print(f"Created content item with ID: {content_item.id}")
                # Save file and get or create audio meta
                file_path = MediaUploadService._save_file(
                    file, 'original/audio', content_item.id
                )
                
                # Get the AudioMeta (created by signal) and update it
                audio_meta, created = AudioMeta.objects.get_or_create(
                    content_item=content_item,
                    defaults={
                        'original_file': file_path,
                        'file_size_mb': round(file.size / (1024 * 1024), 2),
                        'processing_status': 'pending'
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    audio_meta.original_file = file_path
                    audio_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    audio_meta.processing_status = 'pending'
                    audio_meta.save()
                
                print(f"Audio meta ID: {audio_meta.id} (created: {created})")

                
                # Queue for background processing
                process_audio_compression.delay(str(audio_meta.id))
                
                logger.info(f"Audio uploaded successfully: {content_item.id}")
                return True, _("Audio uploaded and queued for processing"), content_item
                
        except Exception as e:
            logger.error(f"Error uploading audio: {str(e)}")
            return False, f"{_('Error uploading audio')}: {str(e)}", None
    
    @staticmethod
    def upload_pdf(
        file: UploadedFile,
        title_ar: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process PDF file
        
        Args:
            file: PDF file to upload
            title_ar: Arabic title
            description_ar: Arabic description
            title_en: English title
            description_en: English description
            tag_ids: List of tag UUIDs
            
        Returns:
            Tuple of (success, message, content_item)
        """
        try:
            # Validate file
            is_valid, error_msg = MediaUploadService.validate_file(file, 'pdf')
            if not is_valid:
                return False, error_msg, None
            
            with transaction.atomic():
                # Create content item
                content_item = ContentService.create_content_item(
                    title_ar=title_ar,
                    content_type='pdf',
                    description_ar=description_ar,
                    title_en=title_en,
                    description_en=description_en,
                    tag_ids=tag_ids
                )
                
                # Save file and get or create PDF meta
                file_path = MediaUploadService._save_file(
                    file, 'original/pdf', content_item.id
                )
                
                # Get the PdfMeta (created by signal) and update it
                pdf_meta, created = PdfMeta.objects.get_or_create(
                    content_item=content_item,
                    defaults={
                        'original_file': file_path,
                        'file_size_mb': round(file.size / (1024 * 1024), 2),
                        'processing_status': 'pending'
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    pdf_meta.original_file = file_path
                    pdf_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    pdf_meta.processing_status = 'pending'
                    pdf_meta.save()
                
                # Queue for background processing
                process_pdf_optimization.delay(str(pdf_meta.id))
                
                logger.info(f"PDF uploaded successfully: {content_item.id}")
                return True, _("PDF uploaded and queued for processing"), content_item
                
        except Exception as e:
            logger.error(f"Error uploading PDF: {str(e)}")
            return False, f"{_('Error uploading PDF')}: {str(e)}", None
    
    @staticmethod
    def _save_file(
        file: UploadedFile, 
        subdirectory: str, 
        content_id: str
    ) -> str:
        """
        Save uploaded file to filesystem
        
        Args:
            file: Uploaded file object
            subdirectory: Subdirectory under MEDIA_ROOT
            content_id: Content UUID for unique naming
            
        Returns:
            Relative path to saved file
        """
        # Generate unique filename
        file_extension = Path(file.name).suffix.lower()
        filename = f"{content_id}{file_extension}"
        relative_path = f"{subdirectory}/{filename}"
        
        # Ensure directory exists
        full_dir = Path(settings.MEDIA_ROOT) / subdirectory
        full_dir.mkdir(parents=True, exist_ok=True)
        
        # Save file
        full_path = full_dir / filename
        with open(full_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        logger.debug(f"File saved to {relative_path}")
        return relative_path
    
    @staticmethod
    def delete_media_files(content_item: ContentItem) -> bool:
        """
        Delete all media files associated with a content item
        
        Args:
            content_item: ContentItem instance
            
        Returns:
            True if successful
        """
        try:
            meta = content_item.get_meta_object()
            if not meta:
                return True
            
            files_to_delete = []
            
            if content_item.content_type == 'video':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                # HLS files would be in directories, handle separately
                
            elif content_item.content_type == 'audio':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                if meta.compressed_file:
                    files_to_delete.append(meta.compressed_file.path)
                    
            elif content_item.content_type == 'pdf':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                if meta.optimized_file:
                    files_to_delete.append(meta.optimized_file.path)
            
            # Delete files
            for file_path in files_to_delete:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Deleted file: {file_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting media files for {content_item.id}: {str(e)}")
            return False