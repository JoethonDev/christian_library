from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import DetailView
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
import json
import logging

from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from .services import ContentService, MediaMetaService
from core.utils.media_security import media_signer, get_secure_media_url, get_hls_token
from core.utils.exceptions import (
    ContentNotFoundError, 
    InvalidContentTypeError,
    MediaSecurityError
)

logger = logging.getLogger(__name__)


class SecureMediaView(View):
    """
    Secure media delivery with signed URL validation
    """
    
    def get(self, request, content_type, content_uuid):
        """
        Generate signed URL for media access
        
        Args:
            content_type: 'video', 'audio', or 'pdf'
            content_uuid: UUID of the content item
        """
        try:
            # Validate content type
            if content_type not in ['video', 'audio', 'pdf']:
                return JsonResponse({
                    'error': True,
                    'message': str(_('Invalid content type'))
                }, status=400)
            
            # Get content item using service
            content_item = ContentService.get_content_by_id(content_uuid, content_type)
            
            # Get the appropriate meta object and file path
            file_path = self._get_media_file_path(content_item, content_type)
            if not file_path:
                return JsonResponse({
                    'error': True,
                    'message': str(_('Media file not available'))
                }, status=404)
            
            # Generate signed URL
            user_id = str(request.user.id) if request.user.is_authenticated else None
            expiry_hours = 24 if content_type == 'pdf' else 4  # Longer for PDFs
            
            signed_url = get_secure_media_url(
                media_path=file_path,
                expiry_hours=expiry_hours,
                user_id=user_id
            )
            
            return JsonResponse({
                'url': signed_url,
                'content_type': content_type,
                'title': content_item.get_title(),
                'expires_in_hours': expiry_hours,
                'error': False
            })
            
        except ContentNotFoundError:
            return JsonResponse({
                'error': True,
                'message': str(_('Content not found'))
            }, status=404)
        except InvalidContentTypeError as e:
            return JsonResponse({
                'error': True,
                'message': str(_('Content type mismatch'))
            }, status=400)
        except Exception as e:
            logger.error(f"Error generating secure media URL: {str(e)}")
            return JsonResponse({
                'error': True,
                'message': str(_('Internal server error'))
            }, status=500)
    
    def _get_media_file_path(self, content_item, content_type):
        """Get the appropriate file path for the content type"""
        try:
            if content_type == 'video':
                meta = MediaMetaService.get_video_meta(content_item.id)
                return meta.original_file.name if meta.original_file else None
                
            elif content_type == 'audio':
                meta = MediaMetaService.get_audio_meta(content_item.id)
                # Prefer compressed version if available
                if meta.compressed_file:
                    return meta.compressed_file.name
                return meta.original_file.name if meta.original_file else None
                
            elif content_type == 'pdf':
                meta = MediaMetaService.get_pdf_meta(content_item.id)
                # Prefer optimized version if available
                if meta.optimized_file:
                    return meta.optimized_file.name
                return meta.original_file.name if meta.original_file else None
                
            return None
            
        except Exception:
            return None


# API Views for mobile/frontend consumption
class ContentListAPIView(View):
    """API view for content listing with filtering and pagination"""
    
    def get(self, request):
        """Get filtered content list"""
        try:
            # Extract query parameters
            content_type = request.GET.get('type')
            module_id = request.GET.get('module')
            search_query = request.GET.get('search', '').strip()
            language = request.GET.get('lang', 'ar')
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 20))
            
            # Get content using service
            content_items = ContentService.get_content_list(
                content_type=content_type,
                module_id=module_id,
                search_query=search_query,
                language=language
            )
            
            # Serialize data
            data = []
            for item in content_items:
                item_data = {
                    'id': str(item.id),
                    'title': item.get_title(language),
                    'description': item.get_description(language),
                    'content_type': item.content_type,
                    # Module functionality has been removed
                    # 'module': {
                    #     'id': str(item.module.id),
                    #     'title': item.module.get_title(language)
                    # },
                    'created_at': item.created_at.isoformat(),
                }
                data.append(item_data)
            
            return JsonResponse({
                'success': True,
                'data': data,
            })
            
        except Exception as e:
            logger.error(f"Error in content list API: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(_('Internal server error'))
            }, status=500)