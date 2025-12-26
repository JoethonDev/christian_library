import logging
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q, Count
from django.utils.translation import gettext as _
from django.utils.translation import get_language
from django.views.generic import ListView
from django.views.decorators.http import require_http_methods
from django.template.loader import render_to_string
from rest_framework.decorators import api_view
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchHeadline

from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag


def home(request):
    """Homepage with featured content and categories"""
    current_language = get_language()
    
    # Get latest content
    latest_videos = ContentItem.objects.filter(
        content_type='video', 
        is_active=True
    ).select_related('videometa').prefetch_related('tags').order_by('-created_at')[:6]
    
    latest_audios = ContentItem.objects.filter(
        content_type='audio',
        is_active=True
    ).select_related('audiometa').prefetch_related('tags').order_by('-created_at')[:6]
    
    latest_pdfs = ContentItem.objects.filter(
        content_type='pdf',
        is_active=True
    ).select_related('pdfmeta').prefetch_related('tags').order_by('-created_at')[:6]
    
    # Add unified metadata for each content item
    for item in latest_videos:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
    
    for item in latest_audios:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
        
    for item in latest_pdfs:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
    
    # Get popular tags with unified names
    popular_tags = Tag.objects.filter(
        is_active=True
    ).annotate(
        content_count=Count('contentitem', filter=Q(contentitem__is_active=True))
    ).order_by('-content_count')[:8]
    
    for tag in popular_tags:
        tag.name = tag.get_name(current_language)
    
    # Get content statistics
    stats = {
        'total_videos': ContentItem.objects.filter(content_type='video', is_active=True).count(),
        'total_audios': ContentItem.objects.filter(content_type='audio', is_active=True).count(),
        'total_pdfs': ContentItem.objects.filter(content_type='pdf', is_active=True).count(),
        'total_tags': Tag.objects.filter(is_active=True).count(),
    }
    
    context = {
        'latest_videos': latest_videos,
        'latest_audios': latest_audios,
        'latest_pdfs': latest_pdfs,
        'popular_tags': popular_tags,
        'stats': stats,
    }
    
    return render(request, 'frontend_api/home.html', context)


def videos(request):
    """Video listing page with filtering and pagination"""
    current_language = get_language()
    
    videos_qs = ContentItem.objects.filter(
        content_type='video',
        is_active=True
    ).select_related('videometa').prefetch_related('tags').order_by('-created_at')
    
    # Filtering
    search_query = request.GET.get('search', '').strip()
    tag_filter = request.GET.get('tag', '').strip()
    
    if search_query:
        videos_qs = videos_qs.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query) |
            Q(description_ar__icontains=search_query) |
            Q(description_en__icontains=search_query) |
            Q(tags__name_ar__icontains=search_query) |
            Q(tags__name_en__icontains=search_query)
        ).distinct()
    
    if tag_filter:
        videos_qs = videos_qs.filter(tags__id=tag_filter)
    
    # Pagination
    paginator = Paginator(videos_qs, 12)  # 12 videos per page
    page_number = request.GET.get('page', 1)
    videos_page = paginator.get_page(page_number)
    
    # Add unified metadata for video items
    for video in videos_page:
        video.title = video.get_title(current_language)
        video.description = video.get_description(current_language)
    
    # Get available tags for filter with unified names
    available_tags = Tag.objects.filter(
        is_active=True,
        contentitem__content_type='video',
        contentitem__is_active=True
    ).distinct().order_by('name_ar')
    
    for tag in available_tags:
        tag.name = tag.get_name(current_language)
    
    context = {
        'videos': videos_page,
        'search_query': search_query,
        'tag_filter': tag_filter,
        'available_tags': available_tags,
        'total_count': videos_qs.count(),
    }
    
    # HTMX partial template for infinite scroll
    if request.headers.get('HX-Request'):
        return render(request, 'frontend_api/partials/video_grid.html', context)
    
    return render(request, 'frontend_api/videos.html', context)


def video_detail(request, video_uuid):
    """Individual video detail page"""
    video = get_object_or_404(
        ContentItem, 
        id=video_uuid, 
        content_type='video',
        is_active=True
    )
    
    current_language = get_language()
    video.title = video.get_title(current_language)
    video.description = video.get_description(current_language)
    
    # Get related videos with similar tags
    video_tags = video.tags.all()
    related_videos = ContentItem.objects.filter(
        tags__in=video_tags,
        content_type='video',
        is_active=True
    ).exclude(id=video.id).select_related('videometa').distinct()[:4]
    
    # Add unified metadata for related videos
    for item in related_videos:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
    
    context = {
        'video': video,
        'related_videos': related_videos,
    }
    
    return render(request, 'frontend_api/video_detail.html', context)


def audios(request):
    """Audio listing page with filtering and pagination"""
    current_language = get_language()
    
    audios_qs = ContentItem.objects.filter(
        content_type='audio',
        is_active=True
    ).select_related('audiometa').prefetch_related('tags').order_by('-created_at')
    
    # Filtering
    search_query = request.GET.get('search', '').strip()
    tag_filter = request.GET.get('tag', '').strip()
    
    if search_query:
        audios_qs = audios_qs.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query) |
            Q(description_ar__icontains=search_query) |
            Q(description_en__icontains=search_query) |
            Q(tags__name_ar__icontains=search_query) |
            Q(tags__name_en__icontains=search_query)
        ).distinct()
    
    if tag_filter:
        audios_qs = audios_qs.filter(tags__id=tag_filter)
    
    # Pagination
    paginator = Paginator(audios_qs, 12)
    page_number = request.GET.get('page', 1)
    audios_page = paginator.get_page(page_number)
    
    # Add unified metadata for audio items
    for audio in audios_page:
        audio.title = audio.get_title(current_language)
        audio.description = audio.get_description(current_language)
    
    # Get available tags for filter with unified names
    available_tags = Tag.objects.filter(
        is_active=True,
        contentitem__content_type='audio',
        contentitem__is_active=True
    ).distinct().order_by('name_ar')
    
    for tag in available_tags:
        tag.name = tag.get_name(current_language)
    
    context = {
        'audios': audios_page,
        'search_query': search_query,
        'tag_filter': tag_filter,
        'available_tags': available_tags,
        'total_count': audios_qs.count(),
    }
    
    # HTMX partial template
    if request.headers.get('HX-Request'):
        return render(request, 'frontend_api/partials/audio_grid.html', context)
    
    return render(request, 'frontend_api/audios.html', context)


def audio_detail(request, audio_uuid):
    """Individual audio detail page"""
    audio = get_object_or_404(
        ContentItem,
        id=audio_uuid,
        content_type='audio',
        is_active=True
    )
    
    current_language = get_language()
    audio.title = audio.get_title(current_language)
    audio.description = audio.get_description(current_language)
    
    # Get related audios with similar tags
    audio_tags = audio.tags.all()
    related_audios = ContentItem.objects.filter(
        tags__in=audio_tags,
        content_type='audio',
        is_active=True
    ).exclude(id=audio.id).select_related('audiometa').distinct()[:4]
    
    # Add unified metadata for related audios
    for item in related_audios:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
    
    context = {
        'audio': audio,
        'related_audios': related_audios,
    }
    
    return render(request, 'frontend_api/audio_detail.html', context)


def pdfs(request):
    """PDF listing page with filtering and pagination"""
    current_language = get_language()
    
    pdfs_qs = ContentItem.objects.filter(
        content_type='pdf',
        is_active=True
    ).select_related('pdfmeta').prefetch_related('tags').order_by('-created_at')
    
    # Filtering
    search_query = request.GET.get('search', '').strip()
    tag_filter = request.GET.get('tag', '').strip()
    
    if search_query:
        pdfs_qs = pdfs_qs.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query) |
            Q(description_ar__icontains=search_query) |
            Q(description_en__icontains=search_query) |
            Q(tags__name_ar__icontains=search_query) |
            Q(tags__name_en__icontains=search_query)
        ).distinct()
    
    if tag_filter:
        pdfs_qs = pdfs_qs.filter(tags__id=tag_filter)
    
    # Pagination
    paginator = Paginator(pdfs_qs, 12)
    page_number = request.GET.get('page', 1)
    pdfs_page = paginator.get_page(page_number)
    
    # Add unified metadata for PDF items
    for pdf in pdfs_page:
        pdf.title = pdf.get_title(current_language)
        pdf.description = pdf.get_description(current_language)
    
    # Get available tags for filter with unified names
    available_tags = Tag.objects.filter(
        is_active=True,
        contentitem__content_type='pdf',
        contentitem__is_active=True
    ).distinct().order_by('name_ar')
    
    for tag in available_tags:
        tag.name = tag.get_name(current_language)
    
    context = {
        'pdfs': pdfs_page,
        'search_query': search_query,
        'tag_filter': tag_filter,
        'available_tags': available_tags,
        'total_count': pdfs_qs.count(),
    }
    
    # HTMX partial template
    if request.headers.get('HX-Request'):
        return render(request, 'frontend_api/partials/pdf_grid.html', context)
    
    return render(request, 'frontend_api/pdfs.html', context)


def pdf_detail(request, pdf_uuid):
    """Individual PDF detail page"""
    pdf = get_object_or_404(
        ContentItem,
        id=pdf_uuid,
        content_type='pdf',
        is_active=True
    )
    
    current_language = get_language()
    pdf.title = pdf.get_title(current_language)
    pdf.description = pdf.get_description(current_language)
    
    # Get related PDFs with similar tags
    pdf_tags = pdf.tags.all()
    related_pdfs = ContentItem.objects.filter(
        tags__in=pdf_tags,
        content_type='pdf',
        is_active=True
    ).exclude(id=pdf.id).select_related('pdfmeta').distinct()[:4]
    
    # Add unified metadata for related PDFs
    for item in related_pdfs:
        item.title = item.get_title(current_language)
        item.description = item.get_description(current_language)
    
    context = {
        'pdf': pdf,
        'related_pdfs': related_pdfs,
    }
    
    return render(request, 'frontend_api/pdf_detail.html', context)


def tag_content(request, tag_id):
    """Tag content listing page showing all content with this tag"""
    tag = get_object_or_404(Tag, id=tag_id, is_active=True)
    
    content_qs = ContentItem.objects.filter(
        tags=tag,
        is_active=True
    ).prefetch_related('tags').order_by('-created_at')
    
    # Optional content type filter
    content_type_filter = request.GET.get('content_type', '').strip()
    if content_type_filter in ['video', 'audio', 'pdf']:
        content_qs = content_qs.filter(content_type=content_type_filter)
    
    # Pagination
    paginator = Paginator(content_qs, 12)
    page_number = request.GET.get('page', 1)
    content_page = paginator.get_page(page_number)
    
    # Get tag statistics
    tag_stats = {
        'total_videos': ContentItem.objects.filter(
            tags=tag, content_type='video', is_active=True
        ).count(),
        'total_audios': ContentItem.objects.filter(
            tags=tag, content_type='audio', is_active=True
        ).count(),
        'total_pdfs': ContentItem.objects.filter(
            tags=tag, content_type='pdf', is_active=True
        ).count(),
    }
    
    context = {
        'tag': tag,
        'content': content_page,
        'content_type_filter': content_type_filter,
        'tag_stats': tag_stats,
        'total_count': content_qs.count(),
    }
    
    return render(request, 'frontend_api/tag_content.html', context)


def search(request):
    """Global search functionality with multilingual support"""
    search_query = request.GET.get('q', '').strip()
    content_type_filter = request.GET.get('content_type', '').strip()
    tag_filter = request.GET.get('tag', '').strip()
    sort_by = request.GET.get('sort', '-created_at').strip()
    
    # Get current language for proper field selection
    current_language = get_language()
    
    results = []
    total_count = 0
    available_tags = Tag.objects.filter(is_active=True).distinct()
    
    if search_query or content_type_filter or tag_filter:
        base_query = ContentItem.objects.filter(is_active=True).prefetch_related('tags')

        # Use FTS for PDFs, fallback to icontains for others
        if search_query:
            if not content_type_filter or content_type_filter == 'pdf':
                # Use FTS for PDFs (Arabic config)
                query = SearchQuery(search_query, config='arabic')
                base_query = base_query.annotate(
                    rank=SearchRank(models.F('search_vector'), query),
                    headline=SearchHeadline(
                        'book_content',
                        query,
                        config='arabic',
                        start_sel='<mark>',
                        stop_sel='</mark>',
                        max_words=30,
                        min_words=10,
                        max_fragments=2,
                        fragment_delimiter=' ... '
                    )
                ).filter(rank__gte=0.1)
                results = base_query.order_by('-rank')
            else:
                # Fallback: icontains for video/audio
                search_conditions = (
                    Q(title_ar__icontains=search_query) |
                    Q(title_en__icontains=search_query) |
                    Q(description_ar__icontains=search_query) |
                    Q(description_en__icontains=search_query) |
                    Q(tags__name_ar__icontains=search_query)
                )
                results = base_query.filter(search_conditions).distinct()
        else:
            results = base_query

        # Filter by content type if specified
        if content_type_filter in ['video', 'audio', 'pdf']:
            results = results.filter(content_type=content_type_filter)

        # Filter by tag if specified
        if tag_filter:
            results = results.filter(tags__id=tag_filter)

        # Sorting
        if sort_by in ['title_ar', 'title_en']:
            results = results.order_by(sort_by)
        elif not search_query or content_type_filter != 'pdf':
            results = results.order_by('-created_at')

        total_count = results.count()

        # Pagination
        paginator = Paginator(results, 12)
        page_number = request.GET.get('page', 1)
        results = paginator.get_page(page_number)
    
    context = {
        'query': search_query,
        'content_type_filter': content_type_filter,
        'tag_filter': tag_filter,
        'sort_by': sort_by,
        'results': results,
        'total_count': total_count,
        'available_tags': available_tags,
        'current_language': current_language,
    }
    
    # HTMX partial for search results
    if request.headers.get('HX-Request'):
        return render(request, 'frontend_api/partials/search_results.html', context)
    
    return render(request, 'frontend_api/search.html', context)


@require_http_methods(["GET"])
def search_autocomplete(request):
    """AJAX autocomplete for search with multilingual support"""
    query = request.GET.get('q', '').strip()
    current_language = get_language()
    
    if len(query) < 2:
        return JsonResponse({'suggestions': []})
    
    # Get suggestions from titles and tag names in both languages
    suggestions = []
    
    # Build search conditions for both Arabic and English
    title_conditions = Q(title_ar__icontains=query) | Q(title_en__icontains=query)
    tag_conditions = Q(name_ar__icontains=query) | Q(name_en__icontains=query)
    
    # Content titles
    content_items = ContentItem.objects.filter(
        is_active=True
    ).filter(title_conditions)
    
    for item in content_items[:5]:
        # Prefer current language, fallback to other language
        if current_language == 'ar':
            title = item.title_ar or item.title_en
        else:
            title = item.title_en or item.title_ar
        if title and title not in suggestions:
            suggestions.append(title)
    
    # Tag names
    tag_items = Tag.objects.filter(
        is_active=True
    ).filter(tag_conditions)
    
    for tag in tag_items[:5]:
        if current_language == 'ar':
            name = tag.name_ar or tag.name_en
        else:
            name = tag.name_en or tag.name_ar
        if name and name not in suggestions:
            suggestions.append(name)
    
    # Limit to 10 suggestions
    suggestions = suggestions[:10]
    
    return JsonResponse({'suggestions': suggestions})



@api_view(['GET'])
def api_health(request):
    """API health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'message': 'Christian Library API is running'
    })


# Media Player Views
def audio_player(request, audio_uuid):
    """HTMX endpoint for audio player"""
    try:
        audio = ContentItem.objects.select_related('audiometa').get(
            id=audio_uuid, content_type='audio', is_active=True
        )
        return render(request, 'components/audio_player.html', {'audio': audio})
    except ContentItem.DoesNotExist:
        # Return HTML error message for HTMX
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
        # Return HTML error message for HTMX
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
    """HTMX endpoint for video player"""
    try:
        video = ContentItem.objects.select_related('videometa').get(
            id=video_uuid, content_type='video', is_active=True
        )
        
        # Get quality parameter from request (default to 'auto')
        quality = request.GET.get('quality', 'auto')
        
        # Debug logging
        logger = logging.getLogger(__name__)
        logger.info(f"Video player requested - Video: {video.id}, Quality: {quality}")

        # Get available qualities for this video
        available_qualities = []
        hls_playlist = None
        if hasattr(video, 'videometa') and video.videometa:
            available_qualities = video.videometa.get_available_qualities()
            hls_playlist = video.videometa.get_hls_playlist(quality)
            logger.info(f"Available qualities: {available_qualities}, HLS playlist: {hls_playlist}")

        context = {
            'video': video,
            'selected_quality': quality,
            'available_qualities': available_qualities,
            'hls_playlist': hls_playlist,
        }

        return render(request, 'components/video_player.html', context)
    except ContentItem.DoesNotExist:
        # Return HTML error message for HTMX
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
        # Return HTML error message for HTMX
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
    """HTMX endpoint for PDF viewer"""
    try:
        pdf = ContentItem.objects.select_related('pdfmeta').get(
            id=pdf_uuid, content_type='pdf', is_active=True
        )
        return render(request, 'components/pdf_viewer.html', {'pdf': pdf})
    except ContentItem.DoesNotExist:
        # Return HTML error message for HTMX
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
        # Return HTML error message for HTMX
        error_html = f'''
        <div class="text-center py-3">
            <div class="mb-2">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 1.5rem;"></i>
            </div>
            <small class="text-muted">Error loading PDF viewer: {str(e)}</small>
        </div>
        '''
        return HttpResponse(error_html, status=500)


# API Endpoints
@api_view(['GET'])
def api_home_data(request):
    """API endpoint for home page data"""
    try:
        # Get featured content
        featured_videos = ContentItem.objects.filter(
            content_type='video', is_active=True
        ).prefetch_related('tags').order_by('-created_at')[:6]
        
        featured_audios = ContentItem.objects.filter(
            content_type='audio', is_active=True
        ).prefetch_related('tags').order_by('-created_at')[:6]
        
        featured_pdfs = ContentItem.objects.filter(
            content_type='pdf', is_active=True
        ).prefetch_related('tags').order_by('-created_at')[:6]
        
        # Get statistics
        stats = {
            'total_videos': ContentItem.objects.filter(content_type='video', is_active=True).count(),
            'total_audios': ContentItem.objects.filter(content_type='audio', is_active=True).count(),
            'total_pdfs': ContentItem.objects.filter(content_type='pdf', is_active=True).count(),
            'total_tags': Tag.objects.filter(is_active=True).count(),
        }
        
        # Format data for JSON response
        data = {
            'featured_videos': [
                {
                    'id': str(video.id),
                    'title': video.title_ar if get_language() == 'ar' else video.title_en,
                    'description': video.description_ar if get_language() == 'ar' else video.description_en,
                    'thumbnail_url': getattr(video.videometa, 'thumbnail_url', None) if hasattr(video, 'videometa') else None,
                    'tags': [tag.get_name() for tag in video.tags.filter(is_active=True)],
                    'created_at': video.created_at.isoformat(),
                } for video in featured_videos
            ],
            'featured_audios': [
                {
                    'id': str(audio.id),
                    'title': audio.title_ar if get_language() == 'ar' else audio.title_en,
                    'description': audio.description_ar if get_language() == 'ar' else audio.description_en,
                    'duration': getattr(audio.audiometa, 'duration_seconds', None) if hasattr(audio, 'audiometa') else None,
                    'tags': [tag.get_name() for tag in audio.tags.filter(is_active=True)],
                    'created_at': audio.created_at.isoformat(),
                } for audio in featured_audios
            ],
            'featured_pdfs': [
                {
                    'id': str(pdf.id),
                    'title': pdf.title_ar if get_language() == 'ar' else pdf.title_en,
                    'description': pdf.description_ar if get_language() == 'ar' else pdf.description_en,
                    'page_count': getattr(pdf.pdfmeta, 'page_count', None) if hasattr(pdf, 'pdfmeta') else None,
                    'tags': [tag.get_name() for tag in pdf.tags.filter(is_active=True)],
                    'created_at': pdf.created_at.isoformat(),
                } for pdf in featured_pdfs
            ],
            'statistics': stats
        }
        
        return JsonResponse({'success': True, 'data': data})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
def api_global_search(request):
    """Global search API endpoint"""
    try:
        query = request.GET.get('q', '')
        content_type = request.GET.get('type', 'all')
        language = request.GET.get('language', get_language())
        
        if not query:
            return JsonResponse({'success': False, 'error': 'Query parameter required'}, status=400)
        
        # Search in content items
        content_items = ContentItem.objects.filter(is_active=True)
        
        # Apply search filters
        if language == 'ar':
            content_items = content_items.filter(
                Q(title_ar__icontains=query) | Q(description_ar__icontains=query) |
                Q(tags__name_ar__icontains=query)
            ).distinct()
        else:
            content_items = content_items.filter(
                Q(title_en__icontains=query) | Q(description_en__icontains=query) |
                Q(tags__name_en__icontains=query)
            ).distinct()
        
        # Filter by content type
        if content_type != 'all':
            content_items = content_items.filter(content_type=content_type)
        
        # Search in tags
        tags = Tag.objects.filter(is_active=True)
        if language == 'ar':
            tags = tags.filter(Q(name_ar__icontains=query) | Q(description_ar__icontains=query))
        else:
            tags = tags.filter(Q(name_en__icontains=query))
        
        # Format results
        results = {
            'tags': [
                {
                    'id': str(tag.id),
                    'name': tag.name_ar if language == 'ar' else tag.name_en or tag.name_ar,
                    'description': tag.description_ar,
                    'color': tag.color,
                    'type': 'tag',
                } for tag in tags[:10]
            ],
            'content': [
                {
                    'id': str(item.id),
                    'title': item.title_ar if language == 'ar' else item.title_en,
                    'description': item.description_ar if language == 'ar' else item.description_en,
                    'type': item.content_type,
                    'tags': [tag.get_name(language) for tag in item.tags.filter(is_active=True)],
                } for item in content_items[:20]
            ]
        }
        
        return JsonResponse({'success': True, 'results': results})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
def api_content_stats(request):
    """Content statistics API endpoint"""
    try:
        stats = {
            'total_content': ContentItem.objects.filter(is_active=True).count(),
            'total_videos': ContentItem.objects.filter(content_type='video', is_active=True).count(),
            'total_audios': ContentItem.objects.filter(content_type='audio', is_active=True).count(),
            'total_pdfs': ContentItem.objects.filter(content_type='pdf', is_active=True).count(),
            'total_tags': Tag.objects.filter(is_active=True).count(),
            'content_by_tag': []
        }
        
        # Get content count by tag
        tags_with_content = Tag.objects.filter(is_active=True).annotate(
            content_count=Count('contentitem', filter=Q(contentitem__is_active=True))
        ).order_by('-content_count')[:10]
        
        stats['content_by_tag'] = [
            {
                'tag': tag.name_ar if get_language() == 'ar' else tag.name_en or tag.name_ar,
                'content_count': tag.content_count,
                'color': tag.color
            } for tag in tags_with_content
        ]
        
        return JsonResponse({'success': True, 'data': stats})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def component_showcase(request):
    """Showcase page for Phase 4 enhanced media components"""
    return render(request, 'frontend_api/component_showcase.html', {
        'page_title': _('Component Showcase - Phase 4 Enhanced Media Components'),
        'meta_description': _('Showcase of enhanced media components with Coptic Orthodox theming and mobile-first responsive design'),
    })