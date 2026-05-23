import os
import boto3
import logging
from typing import Optional, Tuple, Union
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils import timezone
from core.services.r2_service import get_r2_service
try:
    from storages.backends.s3boto3 import S3Boto3Storage
except ImportError:
    # Fallback if django-storages is not available
    S3Boto3Storage = None

logger = logging.getLogger(__name__)


class R2MediaStorage(FileSystemStorage):
    """
    Local media storage backend used by Django file fields.

    R2 uploads are handled explicitly by core.services.r2_service after files
    have been processed locally. Keeping the default storage local preserves
    .path access for video/audio/PDF processing tasks and thumbnails.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_r2 = getattr(settings, 'R2_ENABLED', False)

        if self.use_r2:
            required_settings = ['R2_BUCKET_NAME', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_ENDPOINT_URL']
            missing = [setting for setting in required_settings if not getattr(settings, setting, None)]
            if missing:
                logger.warning(
                    "R2 is enabled but default media storage remains local because settings are missing: %s",
                    ", ".join(missing),
                )
            else:
                logger.info(
                    "R2 is enabled, but default media storage stays local so processing tasks can use local paths; explicit R2 upload service handles cloud sync."
                )


class R2Service:
    """
    Service for managing R2 uploads with status and progress tracking.
    Uses the modular R2Service for all operations.
    """
    
    def __init__(self):
        self._r2_service = get_r2_service()
        self.use_r2 = self._r2_service.enabled
        if self.use_r2:
            self.s3_client = self._r2_service.client
            self.bucket_name = self._r2_service.bucket_name
    
    def upload_file_with_progress(
        self,
        local_file_path: str,
        r2_key: str,
        meta_instance: Union['VideoMeta', 'AudioMeta', 'PdfMeta'],
        field_name: str
    ) -> Tuple[bool, str]:
        """
        Upload file to R2 with progress tracking
        
        Args:
            local_file_path: Path to local file
            r2_key: R2 object key
            meta_instance: Model instance to update progress
            field_name: Field name for R2 URL (e.g., 'r2_original_file_url')
        
        Returns:
            Tuple of (success, message/error)
        """
        if not self.use_r2:
            return False, "R2 not enabled"
        
        try:
            # Update status to uploading
            meta_instance.r2_upload_status = 'uploading'
            meta_instance.r2_upload_progress = 0
            meta_instance.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            
            # Get file size for progress calculation
            file_size = os.path.getsize(local_file_path)
            
            # Upload with progress callback
            def progress_callback(bytes_transferred):
                progress = int((bytes_transferred / file_size) * 100)
                if hasattr(meta_instance, 'r2_upload_progress') and progress > meta_instance.r2_upload_progress:
                    meta_instance.r2_upload_progress = progress
                    meta_instance.save(update_fields=['r2_upload_progress'])
            
            # Use modular R2Service for upload
            success, result = self._r2_service.upload_file(
                local_file_path,
                r2_key,
                callback=progress_callback
            )
            
            if success:
                # Update model with success
                setattr(meta_instance, field_name, result)  # result is the URL
                meta_instance.r2_upload_status = 'completed'
                meta_instance.r2_upload_progress = 100
                meta_instance.save(update_fields=[field_name, 'r2_upload_status', 'r2_upload_progress'])
                
                logger.info(f"Successfully uploaded {local_file_path} to R2: {r2_key}")
                return True, "Upload completed successfully"
            else:
                # Update model with failure
                meta_instance.r2_upload_status = 'failed'
                meta_instance.save(update_fields=['r2_upload_status'])
                return False, result  # result is the error message
            
        except Exception as e:
            logger.error(f"R2 upload failed for {local_file_path}: {str(e)}")
            meta_instance.r2_upload_status = 'failed'
            meta_instance.save(update_fields=['r2_upload_status'])
            return False, f"Upload failed: {str(e)}"

    def upload_video_file(self, video_meta):
        """
        Upload video file to R2
        
        Args:
            video_meta: VideoMeta instance
            
        Returns:
            bool: Success status
        """
        from apps.media_manager.models import VideoMeta
        
        try:
            # Upload original file if it exists
            if video_meta.original_file and video_meta.original_file.name:
                original_path = os.path.join(settings.MEDIA_ROOT, video_meta.original_file.name)
                if os.path.exists(original_path):
                    # Use local relative path as R2 key for consistent nginx mapping
                    r2_key = video_meta.original_file.name
                    success, message = self.upload_file_with_progress(
                        original_path, r2_key, video_meta, 'r2_original_file_url'
                    )
                    if not success:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload video {video_meta.id} to R2: {str(e)}")
            return False
    
    def upload_hls_video(self, video_meta):
        """
        Upload HLS video files to R2
        
        Args:
            video_meta: VideoMeta instance
            
        Returns:
            bool: Success status
        """
        try:
            success_all = True
            
            # Process both 720p and 480p if they exist
            configs = [
                (video_meta.hls_720p_path, 'r2_hls_720p_url', '720p'),
                (video_meta.hls_480p_path, 'r2_hls_480p_url', '480p')
            ]
            
            for playlist_rel_path, r2_url_field, quality in configs:
                if not playlist_rel_path:
                    continue
                    
                playlist_path = os.path.join(settings.MEDIA_ROOT, playlist_rel_path)
                if os.path.exists(playlist_path):
                    # Use local relative path as R2 key for consistent nginx mapping
                    r2_playlist_key = playlist_rel_path
                    
                    # Upload main playlist with progress
                    success, message = self.upload_file_with_progress(
                        playlist_path, r2_playlist_key, video_meta, r2_url_field
                    )
                    
                    if not success:
                        success_all = False
                        continue
                    
                    # Upload segment files from the same directory
                    playlist_dir = os.path.dirname(playlist_path)
                    playlist_rel_dir = os.path.dirname(playlist_rel_path)
                    for file_name in os.listdir(playlist_dir):
                        if file_name.endswith('.ts'):
                            segment_path = os.path.join(playlist_dir, file_name)
                            # Use consistent relative path for segments
                            r2_segment_key = f"{playlist_rel_dir}/{file_name}"
                            try:
                                # Use modular R2Service for segment upload
                                seg_success, seg_result = self._r2_service.upload_file(
                                    segment_path,
                                    r2_segment_key
                                )
                                if not seg_success:
                                    logger.error(f"Failed to upload segment {file_name}: {seg_result}")
                                    success_all = False
                            except Exception as e:
                                logger.error(f"Failed to upload segment {file_name}: {e}")
                                success_all = False
            
            return success_all
            
        except Exception as e:
            logger.error(f"Failed to upload HLS video {video_meta.id} to R2: {str(e)}")
            return False
    
    def upload_audio_file(self, audio_meta):
        """
        Upload audio file to R2
        
        Args:
            audio_meta: AudioMeta instance
            
        Returns:
            bool: Success status
        """
        try:
            # Upload original or compressed audio file
            file_path = None
            if audio_meta.compressed_file and audio_meta.compressed_file.name:
                file_path = os.path.join(settings.MEDIA_ROOT, audio_meta.compressed_file.name)
            elif audio_meta.original_file and audio_meta.original_file.name:
                file_path = os.path.join(settings.MEDIA_ROOT, audio_meta.original_file.name)
            
            if file_path and os.path.exists(file_path):
                # Use local relative path as R2 key for consistent nginx mapping
                rel_path = audio_meta.compressed_file.name if audio_meta.compressed_file and audio_meta.compressed_file.name else audio_meta.original_file.name
                r2_key = rel_path
                
                # Determine which field to update based on file type
                field_name = 'r2_compressed_file_url' if audio_meta.compressed_file and audio_meta.compressed_file.name else 'r2_original_file_url'
                success, message = self.upload_file_with_progress(
                    file_path, r2_key, audio_meta, field_name
                )
                return success
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to upload audio {audio_meta.id} to R2: {str(e)}")
            return False
    
    def upload_pdf_file(self, pdf_meta):
        """
        Upload PDF file to R2
        
        Args:
            pdf_meta: PdfMeta instance
            
        Returns:
            bool: Success status
        """
        try:
            # Upload original PDF file only.
            file_path = None
            if pdf_meta.original_file and pdf_meta.original_file.name:
                file_path = os.path.join(settings.MEDIA_ROOT, pdf_meta.original_file.name)
            
            if file_path and os.path.exists(file_path):
                # Use local relative path as R2 key for consistent nginx mapping
                rel_path = pdf_meta.original_file.name
                r2_key = rel_path
                
                # Always update original file URL.
                field_name = 'r2_original_file_url'
                success, message = self.upload_file_with_progress(
                    file_path, r2_key, pdf_meta, field_name
                )
                return success
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to upload PDF {pdf_meta.id} to R2: {str(e)}")
            return False

    def upload_thumbnail(self, content_item):
        """
        Upload content item thumbnail to R2
        
        Args:
            content_item: ContentItem instance
            
        Returns:
            bool: Success status
        """
        if not self.use_r2 or not content_item.thumbnail:
            return False
            
        try:
            # Use path if it's a FileField/ImageField
            local_path = None
            if hasattr(content_item.thumbnail, 'path'):
                local_path = content_item.thumbnail.path
            else:
                local_path = os.path.join(settings.MEDIA_ROOT, str(content_item.thumbnail))

            if local_path and os.path.exists(local_path):
                # Use local relative path as R2 key
                r2_key = content_item.thumbnail.name
                
                # Simple upload for small thumbnail
                success, result = self._r2_service.upload_file(local_path, r2_key)
                
                if success:
                    content_item.r2_thumbnail_url = result
                    content_item.save(update_fields=['r2_thumbnail_url'])
                    logger.info(f"Successfully uploaded thumbnail for {content_item.id} to R2")
                    return True
                
            return False
        except Exception as e:
            logger.error(f"Failed to upload thumbnail for content {content_item.id} to R2: {str(e)}")
            return False
