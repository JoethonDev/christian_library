"""
Media Management Service Layer - DEPRECATED
This file is kept for backward compatibility.
Use the new service classes in the services/ package instead.
"""
import warnings
from .services import ContentService, MediaMetaService, MediaUploadService

# Deprecation warning
warnings.warn(
    "The services.py file is deprecated. Use 'from apps.media_manager.services import ContentService, MediaUploadService' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Legacy class for backward compatibility
class MediaProcessingService:
    """
    DEPRECATED: Legacy service class
    Use MediaUploadService instead
    """
    
    def __init__(self):
        warnings.warn(
            "MediaProcessingService is deprecated. Use MediaUploadService instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
    def upload_video(self, file, title_ar, title_en="", description_ar="", 
                    description_en="", module_id=None, tags=None):
        """DEPRECATED: Use MediaUploadService.upload_video instead"""
        return MediaUploadService.upload_video(
            file=file,
            title_ar=title_ar,
            module_id=module_id,
            description_ar=description_ar,
            title_en=title_en,
            description_en=description_en,
            tag_ids=tags
        )
    
    def upload_audio(self, file, title_ar, title_en="", description_ar="",
                    description_en="", module_id=None, tags=None):
        """DEPRECATED: Use MediaUploadService.upload_audio instead"""
        return MediaUploadService.upload_audio(
            file=file,
            title_ar=title_ar,
            module_id=module_id,
            description_ar=description_ar,
            title_en=title_en,
            description_en=description_en,
            tag_ids=tags
        )
    
    def upload_pdf(self, file, title_ar, title_en="", description_ar="",
                  description_en="", module_id=None, tags=None):
        """DEPRECATED: Use MediaUploadService.upload_pdf instead"""
        return MediaUploadService.upload_pdf(
            file=file,
            title_ar=title_ar,
            module_id=module_id,
            description_ar=description_ar,
            title_en=title_en,
            description_en=description_en,
            tag_ids=tags
        )
        
    def get_content_stats(self):
        """DEPRECATED: Use ContentService.get_content_statistics instead"""
        return ContentService.get_content_statistics()