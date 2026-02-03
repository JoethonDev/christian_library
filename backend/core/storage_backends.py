import os
import boto3
import logging
from typing import Optional, Tuple, Union
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils import timezone
try:
    from storages.backends.s3boto3 import S3Boto3Storage
except ImportError:
    # Fallback if django-storages is not available
    S3Boto3Storage = None

logger = logging.getLogger(__name__)


class R2MediaStorage:
    """
    Custom storage backend for Cloudflare R2 (S3-compatible).
    Falls back to local storage if R2 is not enabled or fails.
    """
    
    def __init__(self, *args, **kwargs):
        self.use_r2 = getattr(settings, 'R2_ENABLED', False)
        self.fallback_storage = FileSystemStorage()
        
        if self.use_r2:
            try:
                # Validate R2 settings
                required_settings = ['R2_BUCKET_NAME', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_ENDPOINT_URL']
                for setting in required_settings:
                    if not getattr(settings, setting, None):
                        logger.warning(f"R2 setting {setting} not configured, falling back to local storage")
                        self.use_r2 = False
                        break
                
                if self.use_r2 and S3Boto3Storage:
                    # Initialize R2 storage
                    self.r2_storage = S3Boto3Storage(
                        bucket_name=settings.R2_BUCKET_NAME,
                        access_key=settings.R2_ACCESS_KEY_ID,
                        secret_key=settings.R2_SECRET_ACCESS_KEY,
                        endpoint_url=settings.R2_ENDPOINT_URL,
                        region_name=getattr(settings, 'R2_REGION_NAME', 'auto'),
                        default_acl='public-read',
                        file_overwrite=False,
                        custom_domain=False
                    )
                    logger.info("R2 storage backend initialized successfully")
                elif self.use_r2:
                    logger.warning("django-storages not available, falling back to local storage")
                    self.use_r2 = False
                    
            except Exception as e:
                logger.error(f"Failed to initialize R2 storage: {str(e)}, falling back to local storage")
                self.use_r2 = False
    
    def _save(self, name, content):
        """Save file to R2 or local storage with fallback"""
        if self.use_r2:
            try:
                return self.r2_storage._save(name, content)
            except Exception as e:
                logger.error(f"R2 save failed for {name}: {str(e)}, falling back to local storage")
                self.use_r2 = False  # Disable R2 for this session
        
        return self.fallback_storage._save(name, content)
    
    def url(self, name):
        """Get URL for file from R2 or local storage"""
        if self.use_r2 and hasattr(self, 'r2_storage'):
            try:
                return self.r2_storage.url(name)
            except Exception as e:
                logger.error(f"R2 URL generation failed for {name}: {str(e)}, falling back to local storage")
        
        return self.fallback_storage.url(name)
    
    def exists(self, name):
        """Check if file exists in R2 or local storage"""
        if self.use_r2 and hasattr(self, 'r2_storage'):
            try:
                return self.r2_storage.exists(name)
            except Exception as e:
                logger.error(f"R2 exists check failed for {name}: {str(e)}, falling back to local storage")
        
        return self.fallback_storage.exists(name)
    
    def delete(self, name):
        """Delete file from R2 or local storage"""
        if self.use_r2 and hasattr(self, 'r2_storage'):
            try:
                return self.r2_storage.delete(name)
            except Exception as e:
                logger.error(f"R2 delete failed for {name}: {str(e)}, falling back to local storage")
        
        return self.fallback_storage.delete(name)
    
    def size(self, name):
        """Get file size from R2 or local storage"""
        if self.use_r2 and hasattr(self, 'r2_storage'):
            try:
                return self.r2_storage.size(name)
            except Exception as e:
                logger.error(f"R2 size check failed for {name}: {str(e)}, falling back to local storage")
        
        return self.fallback_storage.size(name)


class R2Service:
    """
    Service for managing R2 uploads with status and progress tracking
    """
    
    def __init__(self):
        self.use_r2 = getattr(settings, 'R2_ENABLED', False)
        if self.use_r2:
            try:
                self.s3_client = boto3.client(
                    's3',
                    endpoint_url=settings.R2_ENDPOINT_URL,
                    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, 'R2_REGION_NAME', 'auto')
                )
                self.bucket_name = settings.R2_BUCKET_NAME
                logger.info("R2 service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize R2 service: {str(e)}")
                self.use_r2 = False
    
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
            
            # Perform upload
            self.s3_client.upload_file(
                local_file_path,
                self.bucket_name,
                r2_key,
                Callback=progress_callback
            )
            
            # Generate public URL - use R2.dev format without bucket name
            # Format: https://pub-{public-id}.r2.dev/{r2_key}
            r2_public_url = os.environ.get('R2_PUBLIC_MEDIA_URL')
            if r2_public_url:
                r2_url = f"{r2_public_url}/{r2_key}"
            else:
                # Fallback to constructing from endpoint URL but remove bucket name
                r2_url = f"{settings.R2_ENDPOINT_URL.replace('https://', 'https://pub-').replace('.r2.cloudflarestorage.com', '.r2.dev')}/{r2_key}"
            
            # Update model with success
            setattr(meta_instance, field_name, r2_url)
            meta_instance.r2_upload_status = 'completed'
            meta_instance.r2_upload_progress = 100
            meta_instance.save(update_fields=[field_name, 'r2_upload_status', 'r2_upload_progress'])
            
            logger.info(f"Successfully uploaded {local_file_path} to R2: {r2_key}")
            return True, "Upload completed successfully"
            
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
                                self.s3_client.upload_file(
                                    segment_path,
                                    self.bucket_name,
                                    r2_segment_key
                                )
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
            # Upload optimized or original PDF file
            file_path = None
            if pdf_meta.optimized_file and pdf_meta.optimized_file.name:
                file_path = os.path.join(settings.MEDIA_ROOT, pdf_meta.optimized_file.name)
            elif pdf_meta.original_file and pdf_meta.original_file.name:
                file_path = os.path.join(settings.MEDIA_ROOT, pdf_meta.original_file.name)
            
            if file_path and os.path.exists(file_path):
                # Use local relative path as R2 key for consistent nginx mapping
                rel_path = pdf_meta.optimized_file.name if pdf_meta.optimized_file and pdf_meta.optimized_file.name else pdf_meta.original_file.name
                r2_key = rel_path
                
                # Determine which field to update based on file type
                field_name = 'r2_optimized_file_url' if pdf_meta.optimized_file and pdf_meta.optimized_file.name else 'r2_original_file_url'
                success, message = self.upload_file_with_progress(
                    file_path, r2_key, pdf_meta, field_name
                )
                return success
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to upload PDF {pdf_meta.id} to R2: {str(e)}")
            return False
