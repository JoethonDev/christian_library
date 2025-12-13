from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from django.template.loader import render_to_string
from django.core.cache import cache
from rest_framework.decorators import api_view
import logging

# from apps.courses.models import Course, Module  # Course functionality removed
from apps.media_manager.models import ContentItem
from apps.media_manager.services import ContentService
from core.utils.exceptions import ContentNotFoundError

logger = logging.getLogger(__name__)


@cache_page(60 * 5)  # Cache for 5 minutes
def home(request):
    """Homepage with featured content and categories"""
    try:
        language = get_language()
        
        # Get latest content using optimized queries
        latest_videos = ContentItem.objects.videos_with_meta().active()[:6]
        latest_audios = ContentItem.objects.audios_with_meta().active()[:6]
        latest_pdfs = ContentItem.objects.pdfs_with_meta().active()[:6]
        
        # Get featured courses with content count
        featured_courses = Course.objects.with_modules_and_content().active()[:4]
        
        # Get content statistics (cached)
        stats = ContentService.get_content_statistics()
        
        context = {
            'latest_videos': latest_videos,
            'latest_audios': latest_audios,
            'latest_pdfs': latest_pdfs,
            'featured_courses': featured_courses,
            'stats': stats,
            'language': language,
        }
        
        return render(request, 'frontend_api/home.html', context)
        
    except Exception as e:
        logger.error(f"Error loading home page: {str(e)}")
        # Return minimal context on error
        return render(request, 'frontend_api/home.html', {
            'error_message': _('Error loading content'),
            'stats': {'total_videos': 0, 'total_audios': 0, 'total_pdfs': 0, 'total_courses': 0}
        })


class ContentListView(ListView):
    """Generic content list view with filtering and pagination"""
    model = ContentItem
    template_name = 'frontend_api/content_list.html'
    context_object_name = 'content_items'
    paginate_by = 12
    
    def get_queryset(self):
        """Get filtered and optimized queryset"""
        content_type = self.kwargs.get('content_type')
        queryset = ContentItem.objects.active().with_meta()
        
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        
        # Apply filters
        search_query = self.request.GET.get('search', '').strip()
        course_filter = self.request.GET.get('course', '').strip()
        language = get_language()
        
        if search_query:
            if language == 'ar':
                queryset = queryset.filter(
                    Q(title_ar__icontains=search_query) |
                    Q(description_ar__icontains=search_query) |
                    Q(module__title_ar__icontains=search_query) |
                    Q(module__course__title_ar__icontains=search_query)
                )
            else:
                queryset = queryset.filter(
                    Q(title_en__icontains=search_query) |
                    Q(description_en__icontains=search_query) |
                    Q(module__title_en__icontains=search_query) |
                    Q(module__course__title_en__icontains=search_query)
                )
        
        if course_filter:
            try:
                queryset = queryset.filter(module__course__id=course_filter)
            except:
                pass  # Invalid UUID, ignore filter
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add additional context"""
        context = super().get_context_data(**kwargs)
        content_type = self.kwargs.get('content_type')
        
        # Add filter options
        context.update({
            'content_type': content_type,
            'search_query': self.request.GET.get('search', ''),
            'course_filter': self.request.GET.get('course', ''),
            'available_courses': Course.objects.active(),
            'total_count': self.get_queryset().count(),
            'language': get_language(),
        })
        
        return context


def videos(request):
    """Video listing page"""
    return ContentListView.as_view(
        template_name='frontend_api/videos.html',
        extra_context={'content_type': 'video'}
    )(request, content_type='video')


def audios(request):
    """Audio listing page"""
    return ContentListView.as_view(
        template_name='frontend_api/audios.html',
        extra_context={'content_type': 'audio'}
    )(request, content_type='audio')


def pdfs(request):
    """PDF listing page"""
    return ContentListView.as_view(
        template_name='frontend_api/pdfs.html',
        extra_context={'content_type': 'pdf'}
    )(request, content_type='pdf')


class ContentDetailView(DetailView):
    """Content detail view"""
    model = ContentItem
    template_name = 'frontend_api/content_detail.html'
    context_object_name = 'content_item'
    
    def get_object(self, queryset=None):
        """Get content item using service"""
        content_id = self.kwargs.get('pk')
        content_type = self.kwargs.get('content_type')
        
        try:
            return ContentService.get_content_by_id(content_id, content_type)
        except ContentNotFoundError:
            raise Http404(_("Content not found"))
    
    def get_template_names(self):
        """Get template based on content type"""
        content_type = self.kwargs.get('content_type')
        return [f'frontend_api/{content_type}_detail.html', 'frontend_api/content_detail.html']
    
    def get_context_data(self, **kwargs):
        """Add content-specific context"""
        context = super().get_context_data(**kwargs)
        content_item = self.get_object()
        
        # Add meta object
        context['meta'] = content_item.get_meta_object()
        
        # Add related content
        related_content = ContentItem.objects.active().filter(
            module=content_item.module,
            content_type=content_item.content_type
        ).exclude(id=content_item.id)[:4]
        
        context['related_content'] = related_content
        context['language'] = get_language()
        
        return context


@cache_page(60 * 15)  # Cache for 15 minutes
def search(request):
    """Global search functionality"""
    query = request.GET.get('q', '').strip()
    content_type = request.GET.get('type', '')
    
    if not query:
        return render(request, 'frontend_api/search.html', {
            'search_query': query,
            'results': [],
            'total_count': 0
        })
    
    try:
        # Get search results using service
        language = get_language()
        results = ContentService.get_content_list(
            content_type=content_type or None,
            search_query=query,
            language=language
        )[:50]  # Limit to 50 results
        
        context = {
            'search_query': query,
            'content_type': content_type,
            'results': results,
            'total_count': len(results),
            'language': language,
        }
        
        return render(request, 'frontend_api/search.html', context)
        
    except Exception as e:
        logger.error(f"Error in search: {str(e)}")
        return render(request, 'frontend_api/search.html', {
            'search_query': query,
            'results': [],
            'total_count': 0,
            'error_message': _('Search temporarily unavailable')
        })


# AJAX/API endpoints for dynamic content loading
@require_http_methods(["GET"])
def ajax_content_grid(request, content_type):
    """AJAX endpoint for content grid loading"""
    try:
        page = int(request.GET.get('page', 1))
        search_query = request.GET.get('search', '').strip()
        course_filter = request.GET.get('course', '').strip()
        language = get_language()
        
        # Get content using service
        content_items = ContentService.get_content_list(
            content_type=content_type,
            search_query=search_query if search_query else None,
        )
        
        # Apply course filter if provided
        if course_filter:
            content_items = content_items.filter(module__course__id=course_filter)
        
        # Pagination
        paginator = Paginator(content_items, 12)
        page_obj = paginator.get_page(page)
        
        # Render partial template
        html = render_to_string(f'frontend_api/partials/{content_type}_grid.html', {
            'content_items': page_obj,
            'language': language,
        }, request=request)
        
        return JsonResponse({
            'html': html,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'page_number': page,
            'total_pages': paginator.num_pages,
        })
        
    except Exception as e:
        logger.error(f"Error in AJAX content grid: {str(e)}")
        return JsonResponse({
            'error': str(_('Error loading content')),
        }, status=500)


@require_http_methods(["GET"])
def ajax_search_results(request):
    """AJAX endpoint for search results"""
    try:
        query = request.GET.get('q', '').strip()
        content_type = request.GET.get('type', '')
        language = get_language()
        
        if not query:
            return JsonResponse({'html': '', 'count': 0})
        
        # Get search results
        results = ContentService.get_content_list(
            content_type=content_type or None,
            search_query=query,
            language=language
        )[:20]  # Limit for AJAX
        
        # Render partial template
        html = render_to_string('frontend_api/partials/search_results.html', {
            'results': results,
            'search_query': query,
            'language': language,
        }, request=request)
        
        return JsonResponse({
            'html': html,
            'count': len(results),
        })
        
    except Exception as e:
        logger.error(f"Error in AJAX search: {str(e)}")
        return JsonResponse({
            'error': str(_('Search error')),
        }, status=500)


# Admin dashboard views (moved to separate admin views later)
def admin_dashboard(request):
    """Admin dashboard with statistics"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        stats = ContentService.get_content_statistics()
        
        # Add processing statistics
        processing_stats = {
            'pending_videos': stats.get('processing_videos', 0),
            'pending_audios': stats.get('processing_audios', 0),
            'pending_pdfs': stats.get('processing_pdfs', 0),
        }
        
        context = {
            'stats': stats,
            'processing_stats': processing_stats,
        }
        
        return render(request, 'admin/custom_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        return render(request, 'admin/custom_dashboard.html', {
            'error_message': _('Error loading dashboard'),
            'stats': {'total_content': 0, 'videos': 0, 'audios': 0, 'pdfs': 0}
        })