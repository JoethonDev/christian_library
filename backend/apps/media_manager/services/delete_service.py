import os
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
        try:
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
                # Audio
                elif content_item.content_type == 'audio':
                    audio_meta = getattr(content_item, 'audiometa', None)
                    if audio_meta and audio_meta.original_file:
                        files_to_delete.append(audio_meta.original_file.path)
                # PDF
                elif content_item.content_type == 'pdf':
                    pdf_meta = getattr(content_item, 'pdfmeta', None)
                    if pdf_meta and pdf_meta.original_file:
                        files_to_delete.append(pdf_meta.original_file.path)
                # Delete DB record
                content_item.delete()
                # Delete files/folders asynchronously
                if files_to_delete:
                    delete_files_task.delay(files_to_delete)
                return True, "Content deleted from database. Files deletion scheduled."
        except Exception as e:
            return False, f"Error deleting content: {str(e)}"
