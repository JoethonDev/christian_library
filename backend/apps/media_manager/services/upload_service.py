"""
Media Upload Service Layer
Handles file uploads, validation, and processing initiation
"""
import os
import mimetypes
import uuid
from typing import Dict, Tuple, Optional
from pathlib import Path
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import logging

from ..models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from .content_service import ContentService
from core.utils.exceptions import MediaProcessingError, ValidationError
from core.storage_backends import R2Service
from core.tasks.media_processing import (
    process_video_to_hls,
    process_audio_compression,
    process_pdf_optimization,
    upload_video_to_r2,
    upload_audio_to_r2,
    upload_pdf_to_r2
)

logger = logging.getLogger(__name__)


class MediaUploadService:
    """Service for handling media file uploads and processing"""
    
    # File size limits (in bytes) - Updated to 2GB for all types per API documentation
    MAX_VIDEO_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
    MAX_AUDIO_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
    MAX_PDF_SIZE = 2 * 1024 * 1024 * 1024    # 2GB
    
    # Allowed file types
    ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/avi', 'video/mov', 'video/wmv']
    ALLOWED_AUDIO_TYPES = ['audio/mp3', 'audio/wav', 'audio/m4a', 'audio/aac', 'audio/ogg', 'audio/flac', 'audio/wave', 'audio/x-wav', 'audio/mpeg']
    ALLOWED_PDF_TYPES = ['application/pdf']
    
    def __init__(self):
        self.r2_service = R2Service()
    
    def create_content_item(
        self,
        file_obj,
        title_ar: str,
        title_en: str = "",
        description_ar: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None,
        seo_title_en: str = "",
        seo_title_ar: str = "",
        seo_description_en: str = "",
        seo_description_ar: str = "",
        seo_keywords_en: str = "",
        seo_keywords_ar: str = "",
        transcript: str = "",
        notes: str = "",
        seo_structured_data: str = "",
        document_file = None  # New parameter for supplementary document
    ):
        """Create content item with complete metadata"""
        try:
            # Determine content type from file
            mime_type, _ = mimetypes.guess_type(file_obj.name)
            file_ext = os.path.splitext(file_obj.name)[1].lower()
            
            # More robust detection using both MIME and extension
            if mime_type in self.ALLOWED_VIDEO_TYPES or file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                content_type = 'video'
            elif mime_type in self.ALLOWED_AUDIO_TYPES or file_ext in ['.mp3', '.wav', '.m4a', '.aac', '.ogg']:
                content_type = 'audio'
            elif mime_type in self.ALLOWED_PDF_TYPES or file_ext == '.pdf':
                content_type = 'pdf'
            else:
                return {'success': False, 'error': f'Unsupported file type: {mime_type} ({file_ext})'}
            
            # Validate file
            is_valid, error_msg = self.validate_file(file_obj, content_type)
            if not is_valid:
                return {'success': False, 'error': error_msg}
            
            # If document file provided, extract text synchronously
            book_content_from_doc = None
            if document_file:
                try:
                    from apps.media_manager.services.document_processor_service import DocumentProcessorService
                    doc_processor = DocumentProcessorService()
                    
                    # Validate document
                    doc_mime_type, _ = mimetypes.guess_type(document_file.name)
                    if not doc_mime_type:
                        doc_mime_type = document_file.content_type
                    
                    is_valid_doc, error_msg = doc_processor.validate_document(
                        document_file.size,
                        doc_mime_type,
                        document_file.name
                    )
                    
                    if is_valid_doc:
                        # Save document to temporary location for processing
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(document_file.name)[1]) as tmp_file:
                            for chunk in document_file.chunks():
                                tmp_file.write(chunk)
                            tmp_path = tmp_file.name
                        
                        # Extract text
                        book_content_from_doc = doc_processor.extract_text_from_document(tmp_path, doc_mime_type)
                        
                        # Clean up temp file
                        try:
                            os.unlink(tmp_path)
                        except OSError as e:
                            logger.warning(f"Failed to clean up temp file {tmp_path}: {e}")
                        
                        logger.info(f"Extracted {len(book_content_from_doc) if book_content_from_doc else 0} characters from document")
                    else:
                        logger.warning(f"Document validation failed: {error_msg}")
                except Exception as e:
                    logger.error(f"Error processing document file: {str(e)}", exc_info=True)
            
            # Upload based on type
            if content_type == 'video':
                success, message, content_item = self.upload_video(
                    file_obj, title_ar, title_en, description_ar, description_en,
                    tag_ids, seo_keywords_ar, seo_keywords_en,
                    seo_description_ar, seo_description_en,
                    seo_title_ar, seo_title_en, transcript, notes,
                    seo_title_ar + ',' + seo_title_en if seo_title_en else seo_title_ar,
                    seo_structured_data
                )
            elif content_type == 'audio':
                success, message, content_item = self.upload_audio(
                    file_obj, title_ar, description_ar, title_en, description_en,
                    tag_ids, seo_keywords_ar, seo_keywords_en,
                    seo_description_ar, seo_description_en,
                    seo_title_ar, seo_title_en, transcript, notes,
                    seo_title_ar + ',' + seo_title_en if seo_title_en else seo_title_ar,
                    seo_structured_data
                )
            elif content_type == 'pdf':
                success, message, content_item = self.upload_pdf(
                    file_obj, title_ar, description_ar, title_en, description_en,
                    tag_ids, seo_keywords_ar, seo_keywords_en,
                    seo_description_ar, seo_description_en,
                    seo_title_ar, seo_title_en, transcript, notes,
                    seo_title_ar + ',' + seo_title_en if seo_title_en else seo_title_ar,
                    seo_structured_data
                )
            
            # If document text was extracted, set it as book_content
            # Also save the document file to storage and R2
            if success and book_content_from_doc and content_item and document_file:
                with transaction.atomic():
                    # Save document to storage
                    
                    # Generate unique filename
                    file_ext = os.path.splitext(document_file.name)[1]
                    unique_filename = f"{uuid.uuid4()}{file_ext}"
                    year = timezone.now().year
                    month = timezone.now().month
                    file_path = f"documents/{year}/{month:02d}/{unique_filename}"
                    
                    # Save file
                    saved_path = default_storage.save(file_path, document_file)
                    
                    # Update content item with document metadata and book_content
                    content_item.supplementary_document = saved_path
                    content_item.supplementary_document_name = document_file.name
                    content_item.supplementary_document_size = document_file.size
                    content_item.supplementary_document_type = mimetypes.guess_type(document_file.name)[0] or document_file.content_type
                    content_item.supplementary_document_uploaded_at = timezone.now()
                    content_item.book_content = book_content_from_doc
                    content_item.save(update_fields=[
                        'supplementary_document',
                        'supplementary_document_name',
                        'supplementary_document_size',
                        'supplementary_document_type',
                        'supplementary_document_uploaded_at',
                        'book_content'
                    ])
                    
                    # Update search vector immediately
                    content_item.update_search_vector()
                    content_item.save(update_fields=['search_vector'])
                    
                logger.info(f"Set book_content from document and saved to storage for content item {content_item.id}")
                
                # Note: R2 upload is handled automatically by default_storage if configured
                # The saved_path will point to R2 location when R2 storage backend is active
            elif success and book_content_from_doc and content_item:
                # Just set book_content if document was provided but not saved
                with transaction.atomic():
                    content_item.book_content = book_content_from_doc
                    content_item.save(update_fields=['book_content'])
                    # Update search vector immediately
                    content_item.update_search_vector()
                    content_item.save(update_fields=['search_vector'])
                logger.info(f"Set book_content from document for content item {content_item.id}")
            
            return {
                'success': success,
                'content_item': content_item if success else None,
                'message': message
            }
            
        except Exception as e:
            logger.error(f"Error creating content item: {str(e)}")
            return {'success': False, 'error': str(e)}
    
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
    
    def upload_video(
        self,
        file: UploadedFile,
        title_ar: str,
        title_en: str = "",
        description_ar: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None,
        seo_keywords_ar: str = "",
        seo_keywords_en: str = "",
        seo_meta_description_ar: str = "",
        seo_meta_description_en: str = "",
        seo_title_ar: str = "",
        seo_title_en: str = "",
        transcript: str = "",
        notes: str = "",
        seo_title_suggestions: str = "",
        structured_data: str = ""
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process video file
        ...
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
                    tag_ids=tag_ids,
                    seo_keywords_ar=seo_keywords_ar,
                    seo_keywords_en=seo_keywords_en,
                    seo_meta_description_ar=seo_meta_description_ar,
                    seo_meta_description_en=seo_meta_description_en,
                    seo_title_ar=seo_title_ar,
                    seo_title_en=seo_title_en,
                    transcript=transcript,
                    notes=notes,
                    seo_title_suggestions=seo_title_suggestions,
                    structured_data=structured_data
                )
                
                # Save file and get or create video meta
                file_path = MediaUploadService._save_file(
                    file, 'original/videos', content_item.id
                )
                
                # Get the VideoMeta (created by signal) and update it - optimized with single query
                video_meta, created = VideoMeta.objects.select_related('content_item').get_or_create(
                    content_item=content_item,
                    defaults={
                        'original_file': file_path,
                        'file_size_mb': round(file.size / (1024 * 1024), 2),
                        'processing_status': 'pending',
                        'r2_upload_status': 'pending' if getattr(settings, 'R2_ENABLED', False) else ''
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    video_meta.original_file = file_path
                    video_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    video_meta.processing_status = 'pending'
                    if getattr(settings, 'R2_ENABLED', False):
                        video_meta.r2_upload_status = 'pending'
                    video_meta.save()
                
                # Queue for background processing after commit
                transaction.on_commit(lambda: process_video_to_hls.delay(str(video_meta.id)))
                
                logger.info(f"Video uploaded successfully: {content_item.id}")
                return True, _("Video uploaded and queued for processing"), content_item
                
        except Exception as e:
            logger.error(f"Error uploading video: {str(e)}")
            return False, f"{_('Error uploading video')}: {str(e)}", None
    
    def upload_audio(
        self,
        file: UploadedFile,
        title_ar: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None,
        seo_keywords_ar: str = "",
        seo_keywords_en: str = "",
        seo_meta_description_ar: str = "",
        seo_meta_description_en: str = "",
        seo_title_ar: str = "",
        seo_title_en: str = "",
        transcript: str = "",
        notes: str = "",
        seo_title_suggestions: str = "",
        structured_data: str = ""
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process audio file
        ...
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
                    tag_ids=tag_ids,
                    seo_keywords_ar=seo_keywords_ar,
                    seo_keywords_en=seo_keywords_en,
                    seo_meta_description_ar=seo_meta_description_ar,
                    seo_meta_description_en=seo_meta_description_en,
                    seo_title_ar=seo_title_ar,
                    seo_title_en=seo_title_en,
                    transcript=transcript,
                    notes=notes,
                    seo_title_suggestions=seo_title_suggestions,
                    structured_data=structured_data
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
                        'processing_status': 'pending',
                        'r2_upload_status': 'pending' if getattr(settings, 'R2_ENABLED', False) else ''
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    audio_meta.original_file = file_path
                    audio_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    audio_meta.processing_status = 'pending'
                    if getattr(settings, 'R2_ENABLED', False):
                        audio_meta.r2_upload_status = 'pending'
                    audio_meta.save()

                
                # Queue for background processing after commit
                transaction.on_commit(lambda: process_audio_compression.delay(str(audio_meta.id)))
                
                logger.info(f"Audio uploaded successfully: {content_item.id}")
                return True, _("Audio uploaded and queued for processing"), content_item
                
        except Exception as e:
            logger.error(f"Error uploading audio: {str(e)}")
            return False, f"{_('Error uploading audio')}: {str(e)}", None
    
    def upload_pdf(
        self,
        file: UploadedFile,
        title_ar: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[list] = None,
        seo_keywords_ar: str = "",
        seo_keywords_en: str = "",
        seo_meta_description_ar: str = "",
        seo_meta_description_en: str = "",
        seo_title_ar: str = "",
        seo_title_en: str = "",
        transcript: str = "",
        notes: str = "",
        seo_title_suggestions: str = "",
        structured_data: str = ""
    ) -> Tuple[bool, str, Optional[ContentItem]]:
        """
        Upload and process PDF file
        ...
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
                    tag_ids=tag_ids,
                    seo_keywords_ar=seo_keywords_ar,
                    seo_keywords_en=seo_keywords_en,
                    seo_meta_description_ar=seo_meta_description_ar,
                    seo_meta_description_en=seo_meta_description_en,
                    seo_title_ar=seo_title_ar,
                    seo_title_en=seo_title_en,
                    transcript=transcript,
                    notes=notes,
                    seo_title_suggestions=seo_title_suggestions,
                    structured_data=structured_data
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
                        'processing_status': 'pending',
                        'r2_upload_status': 'pending' if getattr(settings, 'R2_ENABLED', False) else ''
                    }
                )
                
                # If it already existed (from signal), update it with file info
                if not created:
                    pdf_meta.original_file = file_path
                    pdf_meta.file_size_mb = round(file.size / (1024 * 1024), 2)
                    pdf_meta.processing_status = 'pending'
                    if getattr(settings, 'R2_ENABLED', False):
                        pdf_meta.r2_upload_status = 'pending'
                    pdf_meta.save()
                
                # Queue for background processing after commit
                transaction.on_commit(lambda: process_pdf_optimization.delay(str(pdf_meta.id)))
                
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
    
    def _queue_r2_upload(self, meta_instance, content_type):
        """
        Queue R2 upload for a media file using Celery tasks
        
        Args:
            meta_instance: VideoMeta, AudioMeta, or PdfMeta instance
            content_type: 'video', 'audio', or 'pdf'
        """
        try:
            if not self.r2_service.use_r2:
                logger.debug(f"R2 not enabled, skipping upload for {content_type}: {meta_instance.content_item.id}")
                return
            
            # Schedule appropriate Celery task based on content type
            if content_type == 'video':
                upload_video_to_r2.delay(str(meta_instance.id))
                logger.info(f"Queued R2 video upload task for: {meta_instance.content_item.id}")
            elif content_type == 'audio':
                upload_audio_to_r2.delay(str(meta_instance.id))
                logger.info(f"Queued R2 audio upload task for: {meta_instance.content_item.id}")
            elif content_type == 'pdf':
                upload_pdf_to_r2.delay(str(meta_instance.id))
                logger.info(f"Queued R2 PDF upload task for: {meta_instance.content_item.id}")
            else:
                logger.warning(f"Unknown content type for R2 upload: {content_type}")
                
        except Exception as e:
            logger.error(f"Failed to queue R2 upload for {content_type} {meta_instance.content_item.id}: {str(e)}")
            # Update status to failed
            meta_instance.r2_upload_status = 'failed'
            meta_instance.save(update_fields=['r2_upload_status'])
    
    
    def attach_supplementary_document(
        self,
        content_item_id: str,
        document_file: UploadedFile
    ) -> Dict:
        """
        Attach a supplementary document to an existing ContentItem.
        Validates document, uploads to storage, saves metadata, and triggers text extraction.
        
        Args:
            content_item_id: UUID of the ContentItem
            document_file: Uploaded document file (.doc/.docx)
            
        Returns:
            Dict with success status and message
        """
        try:
            # Get the content item
            content_item = ContentItem.objects.get(id=content_item_id)
            
            # Validate document
            from apps.media_manager.services.document_processor_service import DocumentProcessorService
            processor = DocumentProcessorService()
            
            mime_type, _ = mimetypes.guess_type(document_file.name)
            if not mime_type:
                mime_type = document_file.content_type
            
            is_valid, error_msg = processor.validate_document(
                document_file.size,
                mime_type,
                document_file.name
            )
            
            if not is_valid:
                return {'success': False, 'error': error_msg}
            
            # Generate unique filename
            file_ext = os.path.splitext(document_file.name)[1]
            unique_filename = f"{uuid.uuid4()}{file_ext}"
            year = timezone.now().year
            month = timezone.now().month
            file_path = f"documents/{year}/{month:02d}/{unique_filename}"
            
            # Save file
            saved_path = default_storage.save(file_path, document_file)
            
            # Update content item with document metadata
            with transaction.atomic():
                content_item.supplementary_document = saved_path
                content_item.supplementary_document_name = document_file.name
                content_item.supplementary_document_size = document_file.size
                content_item.supplementary_document_type = mime_type
                content_item.supplementary_document_uploaded_at = timezone.now()
                content_item.save(update_fields=[
                    'supplementary_document',
                    'supplementary_document_name',
                    'supplementary_document_size',
                    'supplementary_document_type',
                    'supplementary_document_uploaded_at'
                ])
            
            # Trigger async text extraction which will add to book_content
            from apps.media_manager.tasks import extract_document_text
            extract_document_text.delay(str(content_item.id))
            
            logger.info(f"Successfully attached document {document_file.name} to ContentItem {content_item_id}")
            
            return {
                'success': True,
                'message': 'Document uploaded successfully',
                'document_name': document_file.name,
                'document_size': document_file.size,
                'document_path': saved_path,
                'status': 'processing'
            }
            
        except ContentItem.DoesNotExist:
            return {'success': False, 'error': 'Content item not found'}
        except Exception as e:
            logger.error(f"Error attaching document to {content_item_id}: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def delete_supplementary_document(self, content_item_id: str) -> Dict:
        """
        Delete supplementary document from a ContentItem.
        Removes file from storage and clears metadata.
        NOTE: Does NOT modify book_content - extracted text is preserved.
        
        Args:
            content_item_id: UUID of the ContentItem
            
        Returns:
            Dict with success status and message
        """
        try:
            content_item = ContentItem.objects.get(id=content_item_id)
            
            if not content_item.has_supplementary_document:
                return {'success': False, 'error': 'No document attached'}
            
            # Delete file from storage
            if content_item.supplementary_document:
                try:
                    default_storage.delete(content_item.supplementary_document.name)
                    logger.info(f"Deleted document file: {content_item.supplementary_document.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete document file: {str(e)}")
            
            # Clear metadata but keep book_content and supplementary_document_text
            with transaction.atomic():
                content_item.supplementary_document = None
                content_item.supplementary_document_name = ''
                content_item.supplementary_document_size = None
                content_item.supplementary_document_type = ''
                content_item.supplementary_document_uploaded_at = None
                # NOTE: We keep supplementary_document_text and book_content intact
                content_item.save(update_fields=[
                    'supplementary_document',
                    'supplementary_document_name',
                    'supplementary_document_size',
                    'supplementary_document_type',
                    'supplementary_document_uploaded_at'
                ])
                
                # Update search vector (it will still include book_content)
                content_item.update_search_vector()
                content_item.save(update_fields=['search_vector'])
            
            logger.info(f"Successfully deleted document from ContentItem {content_item_id} (preserved extracted text)")
            
            return {
                'success': True,
                'message': 'Document deleted successfully (extracted text preserved)'
            }
            
        except ContentItem.DoesNotExist:
            return {'success': False, 'error': 'Content item not found'}
        except Exception as e:
            logger.error(f"Error deleting document from {content_item_id}: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def delete_media_files(content_item: ContentItem) -> bool:
        """
        Delete all media files associated with a content item (local and R2)
        
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
            r2_service = R2Service()
            
            if content_item.content_type == 'video':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                # Delete R2 files if they exist
                if hasattr(meta, 'r2_original_file_url') and meta.r2_original_file_url:
                    r2_key = meta.r2_original_file_url.split('/')[-1]
                    try:
                        r2_service.s3_client.delete_object(Bucket=r2_service.bucket_name, Key=r2_key)
                    except Exception as e:
                        logger.warning(f"Failed to delete R2 file {r2_key}: {str(e)}")
                # HLS files would be in directories, handle separately
                
            elif content_item.content_type == 'audio':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                if meta.compressed_file:
                    files_to_delete.append(meta.compressed_file.path)
                # Delete R2 files
                for url_field in ['r2_original_file_url', 'r2_compressed_file_url']:
                    if hasattr(meta, url_field):
                        url = getattr(meta, url_field)
                        if url:
                            r2_key = url.split('/')[-1]
                            try:
                                r2_service.s3_client.delete_object(Bucket=r2_service.bucket_name, Key=r2_key)
                            except Exception as e:
                                logger.warning(f"Failed to delete R2 file {r2_key}: {str(e)}")
                    
            elif content_item.content_type == 'pdf':
                if meta.original_file:
                    files_to_delete.append(meta.original_file.path)
                if meta.optimized_file:
                    files_to_delete.append(meta.optimized_file.path)
                # Delete R2 files
                for url_field in ['r2_original_file_url', 'r2_optimized_file_url']:
                    if hasattr(meta, url_field):
                        url = getattr(meta, url_field)
                        if url:
                            r2_key = url.split('/')[-1]
                            try:
                                r2_service.s3_client.delete_object(Bucket=r2_service.bucket_name, Key=r2_key)
                            except Exception as e:
                                logger.warning(f"Failed to delete R2 file {r2_key}: {str(e)}")
            
            # Delete local files
            for file_path in files_to_delete:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Deleted file: {file_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting media files for {content_item.id}: {str(e)}")
            return False