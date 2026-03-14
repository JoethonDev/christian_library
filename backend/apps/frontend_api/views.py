"""
Frontend API Views - Optimized with Zero N+1 Queries
Refactored to use ContentService layer and eliminate database performance issues.
Each view now uses minimal queries with proper relationship loading.
"""
import logging
from typing import Dict, Any

from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.utils.translation import get_language
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view

from apps.frontend_api.schema_generators import generate_schema_for_content, schema_to_json_ld
from apps.frontend_api.services import ContentService, APIService, ContentLanguageProcessor
from apps.media_manager.analytics import record_content_view
from apps.media_manager.models import ContentItem, Tag
from core.utils.cache_utils import cache_invalidator

# Initialize services
content_service = ContentService()
api_service = APIService()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Class-Based Views (replaces the original 8 FBVs)
# ---------------------------------------------------------------------------

class HomeView(View):
    """Homepage with featured content and categories — 2-3 queries total."""
    template_name = 'frontend_api/home.html'

    def get(self, request):
        try:
            context = cache_invalidator.get_home_context()
            if context:
                return render(request, self.template_name, context)
        except Exception:
            pass
        context = content_service.get_home_page_data()
        try:
            cache_invalidator.set_home_context(context)
        except Exception:
            pass
        return render(request, self.template_name, context)


class ContentListMixin:
    """Shared GET logic for listing views that delegate to ContentService."""
    template_name = None
    partial_template_name = None
    content_type = None
    context_object_name = None  # e.g. 'videos', 'audios', 'pdfs'

    def get(self, request):
        search_query = request.GET.get('search', '').strip()
        tag_filter = request.GET.get('tag', '').strip()
        page = int(request.GET.get('page', 1))
        data = content_service.get_content_listing(
            content_type=self.content_type,
            search_query=search_query,
            tag_filter=tag_filter,
            page=page,
            per_page=12,
        )
        context = {
            self.context_object_name: data['pagination']['page'],
            'page_obj': data['pagination']['page'],
            'is_paginated': data['pagination']['num_pages'] > 1,
            'search_query': search_query,
            'tag_filter': tag_filter,
            'available_tags': data['available_tags'],
            'total_count': data['pagination']['total_count'],
        }
        if request.headers.get('HX-Request'):
            return render(request, self.partial_template_name, context)
        return render(request, self.template_name, context)


class VideoListView(ContentListMixin, View):
    template_name = 'frontend_api/videos.html'
    partial_template_name = 'frontend_api/partials/video_grid.html'
    content_type = 'video'
    context_object_name = 'videos'


class AudioListView(ContentListMixin, View):
    template_name = 'frontend_api/audios.html'
    partial_template_name = 'frontend_api/partials/audio_grid.html'
    content_type = 'audio'
    context_object_name = 'audios'


class PdfListView(ContentListMixin, View):
    template_name = 'frontend_api/pdfs.html'
    partial_template_name = 'frontend_api/partials/pdf_grid.html'
    content_type = 'pdf'
    context_object_name = 'pdfs'


class ContentDetailMixin:
    """Shared GET logic for detail views that delegate to ContentService."""
    template_name = None
    content_type = None
    context_object_name = None
    uuid_kwarg = None

    def get(self, request, **kwargs):
        uuid = kwargs[self.uuid_kwarg]
        try:
            data = content_service.get_content_detail(str(uuid), self.content_type, user=request.user)
            schema = generate_schema_for_content(data['content'], request)
            context = {
                self.context_object_name: data['content'],
                f'related_{self.content_type}s': data['related_content'],
                'schema_json_ld': schema_to_json_ld(schema),
            }
            return render(request, self.template_name, context)
        except ContentItem.DoesNotExist:
            raise Http404(f"{self.content_type.capitalize()} not found")


class VideoDetailView(ContentDetailMixin, View):
    template_name = 'frontend_api/video_detail.html'
    content_type = 'video'
    context_object_name = 'video'
    uuid_kwarg = 'video_uuid'


class AudioDetailView(ContentDetailMixin, View):
    template_name = 'frontend_api/audio_detail.html'
    content_type = 'audio'
    context_object_name = 'audio'
    uuid_kwarg = 'audio_uuid'


class PdfDetailView(ContentDetailMixin, View):
    """PDF detail — overrides get() to preserve the service-failure fallback."""
    template_name = 'frontend_api/pdf_detail.html'
    content_type = 'pdf'
    context_object_name = 'pdf'
    uuid_kwarg = 'pdf_uuid'

    def get(self, request, pdf_uuid):
        try:
            data = content_service.get_content_detail(str(pdf_uuid), 'pdf', user=request.user)
            pdf_schema = generate_schema_for_content(data['content'], request)
            try:
                cache_invalidator.set_related_content(str(pdf_uuid), 'pdf', data['related_content'])
            except Exception:
                pass
            return render(request, self.template_name, {
                'pdf': data['content'],
                'related_pdfs': data['related_content'],
                'schema_json_ld': schema_to_json_ld(pdf_schema),
            })
        except ContentItem.DoesNotExist:
            raise Http404("PDF not found")
        except Http404:
            raise
        except Exception as e:
            logger.error(f"Error in PdfDetailView: {str(e)}")
            pdf = get_object_or_404(ContentItem, id=pdf_uuid, content_type='pdf')
            if not pdf.is_active and not request.user.is_staff:
                raise Http404("Content is not active")
            return render(request, self.template_name, {'pdf': pdf, 'related_pdfs': []})


class TagContentView(View):
    """Tag content listing with optional content_type filter — 2 queries total."""
    template_name = 'frontend_api/tag_content.html'

    def get(self, request, tag_id):
        content_type_filter = request.GET.get('content_type', '').strip()
        page = int(request.GET.get('page', 1))
        data = content_service.get_tag_content(
            tag_id=str(tag_id),
            content_type_filter=content_type_filter,
            page=page,
            per_page=12,
        )
        return render(request, self.template_name, {
            'tag': data['tag'],
            'content': data['pagination']['page'],
            'page_obj': data['pagination']['page'],
            'is_paginated': data['pagination']['num_pages'] > 1,
            'content_type_filter': content_type_filter,
            'tag_stats': data['tag_stats'],
            'total_count': data['pagination']['total_count'],
        })


# ---------------------------------------------------------------------------
# FBVs kept as-is: search, autocomplete, API endpoints, media players
# ---------------------------------------------------------------------------

def search(request):
    """Global search functionality - Optimized to 3 queries max"""
    search_query = request.GET.get('q', '').strip()
    content_type_filter = request.GET.get('content_type', '').strip()
    tag_filter = request.GET.get('tag', '').strip()
    sort_by = request.GET.get('sort', '-created_at').strip()
    page = int(request.GET.get('page', 1))
    
    # Get current language for proper processing
    current_language = get_language()
    
    # Get search results using optimized service
    data = content_service.get_search_results(
        search_query=search_query,
        content_type_filter=content_type_filter,
        tag_filter=tag_filter,
        sort_by=sort_by,
        page=page,
        per_page=12
    )
    
    context = {
        'query': search_query,
        'content_type_filter': content_type_filter,
        'tag_filter': tag_filter,
        'sort_by': sort_by,
        'results': data['pagination']['page'] if data['pagination'] else [],
        'page_obj': data['pagination']['page'] if data['pagination'] else None,
        'is_paginated': data['pagination']['num_pages'] > 1 if data['pagination'] else False,
        'total_count': data['total_count'],
        'available_tags': data['available_tags'],
        'current_language': current_language,
    }
    
    # HTMX partial for search results
    if request.headers.get('HX-Request'):
        return render(request, 'frontend_api/partials/search_results.html', context)
    
    return render(request, 'frontend_api/search.html', context)


@require_http_methods(["GET"])
def search_autocomplete(request):
    """AJAX autocomplete for search - Optimized to 2 queries total"""
    query = request.GET.get('q', '').strip()
    
    # Get suggestions using optimized service
    suggestions = content_service.get_autocomplete_suggestions(query)
    
    return JsonResponse({'suggestions': suggestions})


@api_view(['GET'])
def api_health(request):
    """API health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'message': 'Christian Library API is running'
    })


# Media Player Views - Optimized with single queries
def audio_player(request, audio_uuid):
    """HTMX endpoint for audio player - Single optimized query"""
    try:
        audio = ContentItem.objects.select_related('audiometa').get(
            id=audio_uuid, content_type='audio', is_active=True
        )
        return render(request, 'components/audio_player.html', {'audio': audio})
    except ContentItem.DoesNotExist:
        error_html = '''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Audio not found</small>
        </div>
        '''
        return HttpResponse(error_html, status=404)
    except Exception as e:
        logger.error(f"Audio player error: {str(e)}", exc_info=True)
        error_html = f'''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Error loading audio player: {str(e)}</small>
        </div>
        '''
        return HttpResponse(error_html, status=500)


def video_player(request, video_uuid):
    """HTMX endpoint for video player - Single optimized query"""
    try:
        video = ContentItem.objects.select_related('videometa').get(
            id=video_uuid, content_type='video', is_active=True
        )
        
        # Get quality parameter from request (default to 'auto')
        quality = request.GET.get('quality', 'auto')
        
        # Get available qualities for this video
        available_qualities = []
        hls_playlist = None
        if hasattr(video, 'videometa') and video.videometa:
            available_qualities = video.videometa.get_available_qualities()
            hls_playlist = video.videometa.get_hls_playlist(quality)

        context = {
            'video': video,
            'selected_quality': quality,
            'available_qualities': available_qualities,
            'hls_playlist': hls_playlist,
        }

        return render(request, 'components/video_player.html', context)
    except ContentItem.DoesNotExist:
        error_html = '''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Video not found</small>
        </div>
        '''
        return HttpResponse(error_html, status=404)
    except Exception as e:
        logger.error(f"Video player error: {str(e)}", exc_info=True)
        error_html = f'''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Error loading video player: {str(e)}</small>
        </div>
        '''
        return HttpResponse(error_html, status=500)


def pdf_player(request, pdf_uuid):
    """HTMX endpoint for PDF viewer - Single optimized query"""
    try:
        pdf = ContentItem.objects.select_related('pdfmeta').get(
            id=pdf_uuid, content_type='pdf', is_active=True
        )
        return render(request, 'components/pdf_viewer.html', {'pdf': pdf})
    except ContentItem.DoesNotExist:
        error_html = '''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">PDF not found</small>
        </div>
        '''
        return HttpResponse(error_html, status=404)
    except Exception as e:
        logger.error(f"PDF player error: {str(e)}", exc_info=True)
        error_html = f'''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Error loading PDF viewer: {str(e)}</small>
        </div>
        '''
        return HttpResponse(error_html, status=500)


# API Endpoints - All optimized with service layer
@api_view(['GET'])
def api_home_data(request):
    """API endpoint for home page data - Optimized to 3 queries max"""
    try:
        data = api_service.get_home_api_data()
        return JsonResponse({'success': True, 'data': data})
        
    except Exception as e:
        logger.error(f"API home data error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
def api_global_search(request):
    """Global search API endpoint - Optimized to 3 queries max"""
    try:
        query = request.GET.get('q', '')
        content_type = request.GET.get('type', 'all')
        language = request.GET.get('language', get_language())
        
        if not query:
            return JsonResponse({'success': False, 'error': _('Query parameter required')}, status=400)
        
        results = api_service.get_search_api_data(query, content_type, language)
        return JsonResponse({'success': True, 'results': results})
        
    except Exception as e:
        logger.error(f"API search error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
def api_content_stats(request):
    """Content statistics API endpoint - Optimized to 2 queries total"""
    try:
        stats = api_service.get_statistics_api_data()
        return JsonResponse({'success': True, 'data': stats})
        
    except Exception as e:
        logger.error(f"API stats error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
def api_tag_search(request):
    """
    Tag search API endpoint - Search tags by name or description.
    Query params:
        - q: Search query (required)
        - language: 'ar' or 'en' (optional, auto-detected if not provided)
    Returns: List of matching tags with content counts
    """
    try:
        query = request.GET.get('q', '').strip()
        language = request.GET.get('language', get_language())
        
        if not query:
            return JsonResponse({'success': False, 'error': _('Query parameter required')}, status=400)
        
        # Search tags using optimized manager method
        tags = Tag.objects.search_tags(query, language)[:20]  # Limit to 20 results
        
        # Process tag list for API response
        processor = ContentLanguageProcessor()
        processed_tags = processor.process_tag_list(tags, language)
        
        return JsonResponse({
            'success': True,
            'query': query,
            'count': len(processed_tags),
            'tags': processed_tags
        })
        
    except Exception as e:
        logger.error(f"API tag search error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def component_showcase(request):
    """Showcase page for Phase 4 enhanced media components"""
    from django.utils.translation import gettext as _
    
    return render(request, 'frontend_api/component_showcase.html', {
        'page_title': _('Component Showcase - Phase 4 Enhanced Media Components'),
        'meta_description': _('Showcase of enhanced media components with Coptic Orthodox theming and mobile-first responsive design'),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_track_content_view(request):
    """
    AJAX endpoint for tracking content views.
    Uses POST to avoid caching and ensure accurate tracking.
    Separate from content-serving endpoints to prevent cache interference.
    CSRF exempt as this is called from cached pages.
    """
    import json
    
    try:
        # Parse JSON body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'error': _('Invalid JSON')
            }, status=400)
        
        # Validate required fields
        content_type = data.get('content_type')
        content_id = data.get('content_id')
        
        if not content_type or not content_id:
            return JsonResponse({
                'success': False,
                'error': 'content_type and content_id are required'
            }, status=400)
        
        # Validate content_type
        valid_types = ['video', 'audio', 'pdf', 'static']
        if content_type not in valid_types:
            return JsonResponse({
                'success': False,
                'error': f'Invalid content_type. Must be one of: {", ".join(valid_types)}'
            }, status=400)
        
        # Record the view event (atomic operation)
        try:
            record_content_view(request, content_type, content_id)
        except Exception as e:
            logger.error(f"Error recording content view: {str(e)}", exc_info=True)
            # Don't fail the request if tracking fails
            pass
        
        # Return minimal response
        return JsonResponse({
            'success': True,
            'tracked': True
        })
        
    except Exception as e:
        logger.error(f"Error in api_track_content_view: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)