from django.http import JsonResponse, HttpResponse, Http404, FileResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import DetailView
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
import mimetypes
import json
import logging
import os
from pathlib import Path

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


class DirectMediaServeView(View):
    """
    Direct media file serving with streaming support for HTML5 audio/video elements
    
    Features:
    - HTTP Range request support for efficient seeking
    - Chunked streaming to prevent network overload
    - Adaptive chunk sizes based on file size
    - Proper caching headers for performance
    - Support for audio, video, and PDF files
    
    How it works:
    1. Audio/Video: Supports range requests for seeking and progressive download
    2. PDF: Direct serving with appropriate headers
    3. Large files are served in optimized chunks (8KB - 128KB)
    4. Browser can seek to any position without downloading entire file
    5. Reduces server memory usage and network bandwidth
    
    Range Request Examples:
    - bytes=0-1023: First 1KB
    - bytes=1024-: From byte 1024 to end
    - bytes=-500: Last 500 bytes
    """
    
    def get(self, request, content_type, content_uuid):
        """
        Serve media file with streaming support and range requests
        
        Args:
            content_type: 'video', 'audio', or 'pdf'
            content_uuid: UUID of the content item
        """
        try:
            # Validate content type
            if content_type not in ['video', 'audio', 'pdf']:
                raise Http404('Invalid content type')
            
            # Get content item
            content_item = ContentService.get_content_by_id(content_uuid, content_type)
            
            # Get the appropriate meta object and file path
            file_path = self._get_media_file_path(content_item, content_type)
            if not file_path:
                raise Http404('Media file not available')
            
            # Build full file path
            full_path = os.path.join(settings.MEDIA_ROOT, file_path)
            
            # Check if file exists
            if not os.path.exists(full_path):
                raise Http404('Media file not found on disk')
            
            # Get file size
            file_size = os.path.getsize(full_path)
            
            # Determine content type for HTTP response
            content_type_header, _ = mimetypes.guess_type(full_path)
            if not content_type_header:
                if content_type == 'audio':
                    content_type_header = 'audio/mpeg'
                elif content_type == 'video':
                    content_type_header = 'video/mp4'
                elif content_type == 'pdf':
                    content_type_header = 'application/pdf'
                else:
                    content_type_header = 'application/octet-stream'
            
            # Handle range requests for audio and video streaming
            if content_type in ['audio', 'video']:
                return self._handle_streaming_response(request, full_path, file_size, content_type_header, content_item)
            else:
                # For PDF, serve directly without streaming
                return self._handle_direct_response(full_path, content_type_header, content_item, file_path)
                
        except (ContentNotFoundError, ContentItem.DoesNotExist):
            raise Http404('Content not found')
        except InvalidContentTypeError:
            raise Http404('Content type mismatch')
        except Exception as e:
            logger.error(f"Error serving media file: {str(e)}")
            raise Http404('Error serving media file')
    
    def _handle_streaming_response(self, request, file_path, file_size, content_type, content_item):
        """Handle streaming response with range request support"""
        
        # Parse Range header
        range_header = request.META.get('HTTP_RANGE', '').strip()
        
        if range_header and range_header.startswith('bytes='):
            # Handle range request
            ranges = self._parse_range_header(range_header, file_size)
            if ranges:
                start, end = ranges[0]  # Use first range
                
                # Open file and seek to start position
                try:
                    file_handle = open(file_path, 'rb')
                    file_handle.seek(start)
                    
                    # Read chunk
                    chunk_size = end - start + 1
                    chunk_data = file_handle.read(chunk_size)
                    file_handle.close()
                    
                    # Create partial content response
                    response = HttpResponse(chunk_data, content_type=content_type, status=206)
                    response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                    response['Content-Length'] = str(chunk_size)
                    response['Accept-Ranges'] = 'bytes'
                    response['Cache-Control'] = 'public, max-age=3600'
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"Error reading file range: {e}")
                    # Fall back to full file serving
        
        # No range request or invalid range - serve full file with streaming
        try:
            # Use optimal chunk size based on file size
            chunk_size = self._get_optimal_chunk_size(file_size)
            
            response = HttpResponse(
                self._file_iterator(file_path, chunk_size),
                content_type=content_type
            )
            response['Content-Length'] = str(file_size)
            response['Accept-Ranges'] = 'bytes'
            response['Cache-Control'] = 'public, max-age=3600'
            # Add ETag for better caching
            response['ETag'] = f'"{hash(f"{file_path}:{file_size}")}"'
            
            return response
            
        except Exception as e:
            logger.error(f"Error creating streaming response: {e}")
            raise Http404('Error serving media file')
    
    def _handle_direct_response(self, file_path, content_type, content_item, relative_path):
        """Handle direct file response for non-streaming files like PDFs"""
        response = FileResponse(
            open(file_path, 'rb'),
            content_type=content_type
        )
        
        response['Content-Length'] = os.path.getsize(file_path)
        
        # Set filename for downloads
        filename = f"{content_item.get_title()}.{Path(relative_path).suffix}"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'public, max-age=3600'
        
        return response
    
    def _parse_range_header(self, range_header, file_size):
        """Parse HTTP Range header and return list of (start, end) tuples"""
        try:
            ranges = []
            # Remove 'bytes=' prefix
            ranges_str = range_header[6:]
            
            for range_spec in ranges_str.split(','):
                range_spec = range_spec.strip()
                
                if '-' not in range_spec:
                    continue
                
                start_str, end_str = range_spec.split('-', 1)
                
                # Handle different range formats
                if start_str and end_str:
                    # Both start and end specified: "200-999"
                    start = int(start_str)
                    end = int(end_str)
                elif start_str:
                    # Only start specified: "200-" (from byte 200 to end)
                    start = int(start_str)
                    end = file_size - 1
                elif end_str:
                    # Only end specified: "-500" (last 500 bytes)
                    start = max(0, file_size - int(end_str))
                    end = file_size - 1
                else:
                    continue
                
                # Validate range
                if start < 0 or end >= file_size or start > end:
                    continue
                    
                ranges.append((start, end))
            
            return ranges
            
        except (ValueError, IndexError):
            return []
    
    def _file_iterator(self, file_path, chunk_size=65536):
        """
        Iterator to read file in chunks for streaming
        Using 64KB chunks for optimal performance balance
        """
        try:
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"Error reading file chunks: {e}")
            raise
    
    def _get_optimal_chunk_size(self, file_size):
        """
        Calculate optimal chunk size based on file size
        """
        if file_size < 1024 * 1024:  # < 1MB
            return 8192   # 8KB chunks
        elif file_size < 10 * 1024 * 1024:  # < 10MB
            return 32768  # 32KB chunks
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            return 65536  # 64KB chunks
        else:  # >= 100MB
            return 131072  # 128KB chunks
    
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
                        content_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_streaming()
                        }
                    elif item.content_type == 'audio':
                        content_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_playback()
                        }
                    elif item.content_type == 'pdf':
                        content_data['meta'] = {
                            'page_count': meta.page_count,
                            'file_size_mb': meta.file_size_mb,
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_viewing()
                        }
                
                data.append(content_data)
            
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


class MediaPlayerView(View):
    """
    Embedded media player views for different content types
    """
    
    def get(self, request, content_type, content_uuid):
        """
        Return HTML for embedded media players
        """
        try:
            content_item = get_object_or_404(ContentItem, id=content_uuid)
            
            if content_type == 'video':
                return self._render_video_player(request, content_item)
            elif content_type == 'audio':
                return self._render_audio_player(request, content_item)
            elif content_type == 'pdf':
                return self._render_pdf_viewer(request, content_item)
            else:
                raise Http404("Invalid content type")
                
        except ContentItem.DoesNotExist:
            raise Http404("Content not found")
    
    def _render_video_player(self, request, content_item):
        """Render HLS video player"""
        context = {
            'content_item': content_item,
            'video_meta': content_item.videometa,
            'hls_720p_url': f'/api/media/hls/{content_item.id}/720p',
            'hls_480p_url': f'/api/media/hls/{content_item.id}/480p',
        }
        return render(request, 'media_manager/video_player.html', context)
    
    def _render_audio_player(self, request, content_item):
        """Render audio player"""
        context = {
            'content_item': content_item,
            'audio_meta': content_item.audiometa,
            'audio_url': f'/api/media/secure/audio/{content_item.id}',
        }
        return render(request, 'media_manager/audio_player.html', context)
    
    def _render_pdf_viewer(self, request, content_item):
        """Render PDF viewer"""
        context = {
            'content_item': content_item,
            'pdf_meta': content_item.pdfmeta,
            'pdf_url': f'/api/media/secure/pdf/{content_item.id}',
        }
        return render(request, 'media_manager/pdf_viewer.html', context)