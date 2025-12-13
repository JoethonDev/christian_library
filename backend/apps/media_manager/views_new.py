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


class HLSStreamView(View):
    """
    HLS video streaming with token-based authentication
    """
    
    def get(self, request, video_uuid, quality='720p'):
        """
        Generate HLS streaming URL with authentication token
        """
        try:
            # Validate quality parameter
            if quality not in ['720p', '480p']:
                return JsonResponse({
                    'error': True,
                    'message': str(_('Invalid quality parameter'))
                }, status=400)
            
            # Get video content
            content_item = ContentService.get_content_by_id(video_uuid, 'video')
            video_meta = MediaMetaService.get_video_meta(video_uuid)
            
            # Check if video is ready for streaming
            if not video_meta.is_ready_for_streaming():
                return JsonResponse({
                    'error': True,
                    'message': str(_('Video is not ready for streaming'))
                }, status=404)
            
            # Check if specific quality is available
            hls_path = self._get_hls_path(video_meta, quality)
            if not hls_path:
                return JsonResponse({
                    'error': True,
                    'message': str(_('Requested quality not available'))
                }, status=404)
            
            # Generate HLS token
            user_id = str(request.user.id) if request.user.is_authenticated else None
            hls_token = get_hls_token(video_uuid, user_id, expiry_hours=2)
            
            # Build HLS URL
            hls_url = f"/hls/{hls_path}?token={hls_token}"
            
            return JsonResponse({
                'hls_url': hls_url,
                'quality': quality,
                'title': content_item.get_title(),
                'duration': video_meta.get_duration_formatted(),
                'duration_seconds': video_meta.duration_seconds,
                'token_expires_in_hours': 2,
                'error': False
            })
            
        except ContentNotFoundError:
            return JsonResponse({
                'error': True,
                'message': str(_('Video not found'))
            }, status=404)
        except Exception as e:
            logger.error(f"Error generating HLS stream: {str(e)}")
            return JsonResponse({
                'error': True,
                'message': str(_('Internal server error'))
            }, status=500)
    
    def _get_hls_path(self, video_meta, quality):
        """Get HLS path for the specified quality"""
        if quality == '720p':
            return video_meta.hls_720p_path
        elif quality == '480p':
            return video_meta.hls_480p_path
        return None


@require_http_methods(["GET"])
def auth_check(request):
    """
    Authentication check endpoint for Nginx auth_request
    """
    # Extract token from X-Original-URI header
    original_uri = request.META.get('HTTP_X_ORIGINAL_URI', '')
    
    if '/hls/' in original_uri:
        try:
            # Extract token from URI
            if '?token=' in original_uri:
                token = original_uri.split('?token=')[1].split('&')[0]
                # Extract video UUID from path
                path_parts = original_uri.split('/hls/')[1].split('/')
                video_uuid = path_parts[1] if len(path_parts) > 1 else None
                
                if video_uuid and token:
                    user_id = str(request.user.id) if request.user.is_authenticated else None
                    if media_signer.verify_hls_token(token, video_uuid, user_id):
                        return HttpResponse(status=200)  # Allow access
                        
        except Exception as e:
            logger.warning(f"Auth check failed: {str(e)}")
            
    # Default deny
    return HttpResponse(status=403)


class MediaPlayerView(DetailView):
    """
    Embedded media player views for different content types
    """
    model = ContentItem
    template_name = None
    context_object_name = 'content_item'
    
    def get_object(self, queryset=None):
        """Get content item with proper validation"""
        content_uuid = self.kwargs.get('content_uuid')
        content_type = self.kwargs.get('content_type')
        
        try:
            return ContentService.get_content_by_id(content_uuid, content_type)
        except (ContentNotFoundError, InvalidContentTypeError):
            raise Http404(_("Content not found"))
    
    def get_template_names(self):
        """Get template based on content type"""
        content_type = self.kwargs.get('content_type')
        return [f'media_manager/{content_type}_player.html']
    
    def get_context_data(self, **kwargs):
        """Add content-specific context"""
        context = super().get_context_data(**kwargs)
        content_item = self.get_object()
        content_type = content_item.content_type
        
        # Add meta object to context
        try:
            if content_type == 'video':
                context['meta'] = MediaMetaService.get_video_meta(content_item.id)
                context['hls_720p_url'] = f'/api/media/hls/{content_item.id}/720p'
                context['hls_480p_url'] = f'/api/media/hls/{content_item.id}/480p'
            elif content_type == 'audio':
                context['meta'] = MediaMetaService.get_audio_meta(content_item.id)
                context['audio_url'] = f'/api/media/secure/audio/{content_item.id}'
            elif content_type == 'pdf':
                context['meta'] = MediaMetaService.get_pdf_meta(content_item.id)
                context['pdf_url'] = f'/api/media/secure/pdf/{content_item.id}'
                
        except Exception as e:
            logger.error(f"Error loading media metadata: {str(e)}")
            context['meta'] = None
            
        return context


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
            
            # Pagination
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_items = content_items[start_idx:end_idx]
            
            # Serialize data
            data = []
            for item in paginated_items:
                content_data = {
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
                    'tags': [
                        {'id': str(tag.id), 'name': tag.get_name(language)}
                        for tag in item.tags.all()
                    ]
                }
                
                # Add type-specific metadata
                meta = item.get_meta_object()
                if meta:
                    if item.content_type == 'video':
                        item_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_streaming()
                        }
                    elif item.content_type == 'audio':
                        item_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_playback()
                        }
                    elif item.content_type == 'pdf':
                        item_data['meta'] = {
                            'page_count': meta.page_count,
                            'file_size_mb': meta.file_size_mb,
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_viewing()
                        }
                
                data.append(item_data)
            
            return JsonResponse({
                'success': True,
                'data': data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_items': len(content_items),
                    'has_next': end_idx < len(content_items),
                    'has_previous': page > 1
                }
            })
            
        except Exception as e:
            logger.error(f"Error in content list API: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(_('Internal server error'))
            }, status=500)


class ContentStatsAPIView(View):
    """API view for content statistics"""
    
    def get(self, request):
        """Get content statistics"""
        try:
            # Try to get from cache first
            cache_key = 'content_stats'
            stats = cache.get(cache_key)
            
            if stats is None:
                # Get stats from service
                stats = ContentService.get_content_statistics()
                # Cache for 5 minutes
                cache.set(cache_key, stats, 300)
            
            return JsonResponse({
                'success': True,
                'data': stats
            })
            
        except Exception as e:
            logger.error(f"Error getting content statistics: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(_('Internal server error'))
            }, status=500)