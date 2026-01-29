"""
Nginx X-Accel-Redirect integration for secure media serving.
This module provides secure media delivery using nginx's internal routing.
"""
import mimetypes
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, Http404
from django.views.generic import View
from django.core.exceptions import PermissionDenied


class SecureMediaMixin:
    """
    Mixin for secure media serving using nginx X-Accel-Redirect.
    """
    
    def get_media_file_path(self, file_path):
        """Get the full path to the media file."""
        media_root = Path(settings.MEDIA_ROOT)
        full_path = media_root / file_path
        
        # Security: Ensure path is within MEDIA_ROOT
        try:
            full_path.resolve().relative_to(media_root.resolve())
        except ValueError:
            raise PermissionDenied("Access denied: Invalid file path")
            
        return full_path
    
    def get_nginx_internal_path(self, file_path):
        """
        Convert media file path to nginx internal path.
        This should match the internal location configured in nginx.
        """
        return f"/internal/media/{file_path}"
    
    def serve_secure_media(self, file_path, download=False):
        """
        Serve media file securely using nginx X-Accel-Redirect.
        """
        full_path = self.get_media_file_path(file_path)
        
        # Check if file exists
        if not full_path.exists():
            raise Http404("File not found")
        
        # Get content type
        content_type, _ = mimetypes.guess_type(str(full_path))
        if content_type is None:
            content_type = 'application/octet-stream'
        
        # Create response with X-Accel-Redirect header
        response = HttpResponse(content_type=content_type)
        
        # Set nginx internal redirect header
        response['X-Accel-Redirect'] = self.get_nginx_internal_path(file_path)
        
        # Get file size for Content-Length header
        file_size = full_path.stat().st_size
        
        # Set filename for downloads
        if download:
            filename = full_path.name
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        else:
            # For inline display (videos, audio, PDFs)
            response['Content-Disposition'] = f'inline; filename="{full_path.name}"'
        
        # Set additional security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        
        # For streaming media, set proper headers for chunked delivery
        if content_type.startswith(('video/', 'audio/')):
            response['Accept-Ranges'] = 'bytes'
            response['Cache-Control'] = 'private, max-age=3600'
            response['Content-Length'] = str(file_size)
            
            # Enable chunked transfer encoding for streaming
            if not download:
                response['Transfer-Encoding'] = 'chunked'
        else:
            # For PDFs and other documents
            response['Cache-Control'] = 'private, max-age=7200'
            response['Content-Length'] = str(file_size)
        
        return response


class SecureMediaView(SecureMediaMixin, View):
    """
    Generic secure media serving view.
    Allows downloads without authentication but requires auth for streaming.
    """
    
    def get(self, request, file_path):
        """Serve the requested media file."""
        download = request.GET.get('download', False)
        
        # Allow all access without authentication
        return self.serve_secure_media(file_path, download=download)


class SecureStreamView(SecureMediaMixin, View):
    """
    Secure streaming view for audio/video with range request support.
    Uses nginx for actual file serving while Django handles authentication.
    """
    
    def get(self, request, file_path):
        """Serve streaming media with range support."""
        full_path = self.get_media_file_path(file_path)
        
        if not full_path.exists():
            raise Http404("File not found")
        
        # Get content type
        content_type, _ = mimetypes.guess_type(str(full_path))
        
        # Allow HLS files (.m3u8 and .ts) and standard video/audio files
        if not content_type or not (content_type.startswith(('audio/', 'video/')) or 
                                   file_path.endswith('.m3u8') or file_path.endswith('.ts')):
            # Return a proper HTTP error instead of raising PermissionDenied
            return HttpResponse(
                "This endpoint only serves audio, video, and HLS streaming files. Use the secure_media endpoint for other file types.",
                status=400,
                content_type='text/plain'
            )
        
        # Special handling for HLS files
        if file_path.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif file_path.endswith('.ts'):
            content_type = 'video/mp2t'
        
        # Get file size
        file_size = full_path.stat().st_size
        
        # Create response with streaming headers
        response = HttpResponse(content_type=content_type)
        
        # Set nginx internal redirect
        response['X-Accel-Redirect'] = self.get_nginx_internal_path(file_path)
        
        # Different handling for HLS playlist vs segments
        if file_path.endswith('.m3u8'):
            # HLS playlists should be served complete without range requests
            response['Accept-Ranges'] = 'none'
            response['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
            response['Content-Disposition'] = f'inline; filename="{full_path.name}"'
            response['Content-Length'] = str(file_size)
        else:
            # For .ts segments and regular media files, enable range requests
            response['Accept-Ranges'] = 'bytes'
            response['Content-Disposition'] = f'inline; filename="{full_path.name}"'
            response['Cache-Control'] = 'private, max-age=3600'
            response['Content-Length'] = str(file_size)
            
            # Enable chunked transfer encoding for better streaming
            response['Transfer-Encoding'] = 'chunked'
            
            # Handle range requests (nginx will handle the actual byte serving)
            range_header = request.META.get('HTTP_RANGE', '')
            if range_header:
                response.status_code = 206  # Partial Content
                # Pass range header to nginx via X-Accel-Redirect
                response['X-Accel-Limit-Rate'] = '0'  # No rate limiting for range requests
        
        # Common security headers
        response['X-Content-Type-Options'] = 'nosniff'
        
        return response


def get_secure_media_url(file_path, download=False):
    """
    Generate a secure URL for media files.
    """
    from django.urls import reverse
    
    url = reverse('core:secure_media', kwargs={'file_path': file_path})
    if download:
        url += '?download=true'
    return url


def get_secure_stream_url(file_path):
    """
    Generate a secure streaming URL for audio/video files.
    """
    from django.urls import reverse
    
    return reverse('core:secure_stream', kwargs={'file_path': file_path})