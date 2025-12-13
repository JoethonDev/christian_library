import os
import logging
from django.conf import settings
from django.db import transaction
from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from core.tasks.media_processing import delete_files_task

class MediaProcessingService:
    """
    Service for media file processing and management, including deletion of content and associated files.
    """
    def __init__(self):
        self.media_root = settings.MEDIA_ROOT

    def delete_content(self, content_item):
        """
        Delete content item and all associated files from disk and database (async for files).
        Returns (success: bool, message: str)
        """
        logger = logging.getLogger(__name__)
        try:
            logger.info(f"[MediaProcessingService] Deletion requested for ContentItem id={content_item.id} type={content_item.content_type}")
            with transaction.atomic():
                files_to_delete = []
                # Video
                if content_item.content_type == 'video':
                    video_meta = getattr(content_item, 'videometa', None)
                    if video_meta:
                        if video_meta.original_file:
                            files_to_delete.append(video_meta.original_file.path)
                        if video_meta.hls_720p_path:
                            files_to_delete.append(os.path.join(self.media_root, video_meta.hls_720p_path))
                        if video_meta.hls_480p_path:
                            files_to_delete.append(os.path.join(self.media_root, video_meta.hls_480p_path))
                    logger.info(f"[MediaProcessingService] Video files to delete: {files_to_delete}")
                # Audio
                elif content_item.content_type == 'audio':
                    audio_meta = getattr(content_item, 'audiometa', None)
                    if audio_meta and audio_meta.original_file:
                        files_to_delete.append(audio_meta.original_file.path)
                    logger.info(f"[MediaProcessingService] Audio files to delete: {files_to_delete}")
                # PDF
                elif content_item.content_type == 'pdf':
                    pdf_meta = getattr(content_item, 'pdfmeta', None)
                    if pdf_meta and pdf_meta.original_file:
                        files_to_delete.append(pdf_meta.original_file.path)
                    logger.info(f"[MediaProcessingService] PDF files to delete: {files_to_delete}")
                # Delete DB record
                content_item.delete()
                logger.info(f"[MediaProcessingService] ContentItem id={content_item.id} deleted from database.")
                # Delete files/folders asynchronously
                if files_to_delete:
                    logger.info(f"[MediaProcessingService] Scheduling async deletion for: {files_to_delete}")
                    delete_files_task.delay(files_to_delete)
                else:
                    logger.info(f"[MediaProcessingService] No files to delete for ContentItem id={content_item.id}")
                return True, "Content deleted from database. Files deletion scheduled."
        except Exception as e:
            logger.error(f"[MediaProcessingService] Error deleting content id={content_item.id}: {str(e)}")
            return False, f"Error deleting content: {str(e)}"
