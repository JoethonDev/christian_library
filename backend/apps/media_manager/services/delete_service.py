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

    def delete_local_file_only(self, content_item):
        """
        Delete ONLY local files for content item, keeping database record and R2 copy.
        Returns (success: bool, message: str)
        """
        logger = logging.getLogger(__name__)
        try:
            logger.info(f"[MediaProcessingService] Local file deletion requested for ContentItem id={content_item.id}")
            
            files_to_delete = []
            meta = None
            
            if content_item.content_type == 'video':
                meta = getattr(content_item, 'videometa', None)
                if meta:
                    if not meta.r2_original_video_url:
                        return False, "Cannot delete local file: Not yet uploaded to R2."
                    if meta.original_file:
                        files_to_delete.append(meta.original_file.path)
                    if meta.hls_720p_path:
                        files_to_delete.append(os.path.join(self.media_root, meta.hls_720p_path))
                    if meta.hls_480p_path:
                        files_to_delete.append(os.path.join(self.media_root, meta.hls_480p_path))
            
            elif content_item.content_type == 'audio':
                meta = getattr(content_item, 'audiometa', None)
                if meta:
                    if not meta.r2_original_audio_url:
                        return False, "Cannot delete local file: Not yet uploaded to R2."
                    if meta.original_file:
                        files_to_delete.append(meta.original_file.path)
            
            elif content_item.content_type == 'pdf':
                meta = getattr(content_item, 'pdfmeta', None)
                if meta:
                    if not meta.r2_original_file_url:
                        return False, "Cannot delete local file: Not yet uploaded to R2."
                    if meta.original_file:
                        files_to_delete.append(meta.original_file.path)
                    if meta.optimized_file:
                        files_to_delete.append(meta.optimized_file.path)

            if not files_to_delete:
                return False, "No local files found to delete."

            # Clear the FileField values in DB without deleting the record
            if meta:
                if content_item.content_type == 'video':
                    meta.original_file.name = ''
                    # Also clear HLS paths as they are local too
                    meta.hls_720p_path = ''
                    meta.hls_480p_path = ''
                elif content_item.content_type == 'audio':
                    meta.original_file.name = ''
                elif content_item.content_type == 'pdf':
                    meta.original_file.name = ''
                    meta.optimized_file.name = ''
                meta.save()

            # Schedule physical deletion
            delete_files_task.delay(files_to_delete)
            
            return True, "Local files deletion scheduled. R2 copy and database record preserved."

        except Exception as e:
            logger.error(f"[MediaProcessingService] Error deleting local files for content id={content_item.id}: {str(e)}")
            return False, f"Error deleting local files: {str(e)}"
