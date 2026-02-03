from django.http import JsonResponse
from django.views import View
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
import logging

from .models import ContentItem
from .services.content_service import ContentService

logger = logging.getLogger(__name__)


# API Views for mobile/frontend consumption
class ContentListAPIView(View):
    """API view for content listing with filtering and pagination"""
    
    def get(self, request):
        """Get filtered content list"""
        try:
            # Extract query parameters
            content_type = request.GET.get('type')
            search_query = request.GET.get('search', '').strip()
            language = request.GET.get('lang', 'ar')
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 20))
            
            # Get content using service
            content_items = ContentService.get_content_list(
                content_type=content_type,
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
                    'created_at': item.created_at.isoformat(),
                    'tags': [
                        {'id': str(tag.id), 'name': tag.get_name(language)}
                        for tag in item.tags.all()
                    ]
                }
                
                # Add type-specific metadata using already loaded meta to avoid N+1 queries
                try:
                    if item.content_type == 'video':
                        meta = item.videometa
                        content_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_streaming()
                        }
                    elif item.content_type == 'audio':
                        meta = item.audiometa
                        content_data['meta'] = {
                            'duration': meta.get_duration_formatted(),
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_playback()
                        }
                    elif item.content_type == 'pdf':
                        meta = item.pdfmeta
                        content_data['meta'] = {
                            'page_count': meta.page_count,
                            'file_size_mb': meta.file_size_mb,
                            'processing_status': meta.processing_status,
                            'is_ready': meta.is_ready_for_viewing()
                        }
                except AttributeError:
                    # Fallback if meta not loaded (shouldn't happen with optimized service)
                    logger.warning(f"Meta not loaded for content {item.id}")
                    content_data['meta'] = None
                
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
