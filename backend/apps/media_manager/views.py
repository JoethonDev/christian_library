from django.http import JsonResponse
from django.views import View
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models
import logging
import re

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


class PDFContentSearchAPIView(View):
    """
    API view for searching within PDF content.
    Provides full-text search with context snippets and highlighting.
    """
    
    def get(self, request):
        """
        Search within PDF content and return results with context.
        
        Query parameters:
        - q: Search query (required)
        - page: Page number for pagination (default: 1)
        - page_size: Results per page (default: 20, max: 100)
        - language: Language for display (default: 'ar')
        """
        try:
            # Extract and validate query parameters
            search_query = request.GET.get('q', '').strip()
            if not search_query:
                return JsonResponse({
                    'success': False,
                    'error': str(_('Search query is required'))
                }, status=400)
            
            page = int(request.GET.get('page', 1))
            page_size = min(int(request.GET.get('page_size', 20)), 100)
            language = request.GET.get('language', 'ar')
            
            # PostgreSQL Full-Text Search with Arabic configuration
            from django.contrib.postgres.search import SearchQuery, SearchRank
            from django.db import connection
            
            # Check if PostgreSQL is available
            if 'postgresql' not in connection.settings_dict['ENGINE']:
                # Fallback to simple search
                results_qs = ContentItem.objects.filter(
                    content_type='pdf',
                    is_active=True,
                    book_content__icontains=search_query
                ).select_related('pdfmeta').prefetch_related('tags')
            else:
                # Use PostgreSQL FTS with Arabic config
                search_query_obj = SearchQuery(search_query, config='arabic')
                results_qs = ContentItem.objects.filter(
                    content_type='pdf',
                    is_active=True,
                    search_vector__isnull=False
                ).annotate(
                    rank=SearchRank(models.F('search_vector'), search_query_obj)
                ).filter(
                    rank__gte=0.1
                ).select_related('pdfmeta').prefetch_related('tags').order_by('-rank')
            
            # Get total count
            total_count = results_qs.count()
            
            # Pagination
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_results = results_qs[start_idx:end_idx]
            
            # Format results with context snippets
            results_data = []
            for item in paginated_results:
                # Extract context snippet around the search term
                snippet = self._extract_context_snippet(
                    item.book_content, 
                    search_query, 
                    context_length=200
                )
                
                result_data = {
                    'id': str(item.id),
                    'title': item.get_title(language),
                    'description': item.get_description(language),
                    'snippet': snippet,
                    'highlighted_snippet': self._highlight_text(snippet, search_query),
                    'created_at': item.created_at.isoformat(),
                    'tags': [
                        {'id': str(tag.id), 'name': tag.get_name(language)}
                        for tag in item.tags.all()
                    ],
                }
                
                # Add PDF metadata
                try:
                    meta = item.pdfmeta
                    result_data['meta'] = {
                        'page_count': meta.page_count,
                        'file_size_mb': meta.file_size_mb,
                        'processing_status': meta.processing_status,
                    }
                except AttributeError:
                    result_data['meta'] = None
                
                results_data.append(result_data)
            
            return JsonResponse({
                'success': True,
                'query': search_query,
                'results': results_data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': (total_count + page_size - 1) // page_size,
                    'has_next': end_idx < total_count,
                    'has_previous': page > 1
                }
            })
            
        except ValueError as e:
            logger.error(f"Invalid parameter in PDF search: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(_('Invalid parameter value'))
            }, status=400)
        except Exception as e:
            logger.error(f"Error in PDF content search: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(_('Internal server error'))
            }, status=500)
    
    def _extract_context_snippet(self, text: str, query: str, context_length: int = 200) -> str:
        """
        Extract a context snippet around the search query.
        
        Args:
            text: Full text content
            query: Search query
            context_length: Length of context on each side of the match
            
        Returns:
            Context snippet with the search term
        """
        if not text or not query:
            return ""
        
        # Normalize for case-insensitive search
        text_lower = text.lower()
        query_lower = query.lower()
        
        # Find the first occurrence
        match_pos = text_lower.find(query_lower)
        
        if match_pos == -1:
            # If exact match not found, return beginning of text
            return text[:context_length * 2] + ("..." if len(text) > context_length * 2 else "")
        
        # Calculate snippet boundaries
        start = max(0, match_pos - context_length)
        end = min(len(text), match_pos + len(query) + context_length)
        
        # Extract snippet
        snippet = text[start:end]
        
        # Add ellipsis if needed
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        
        return snippet.strip()
    
    def _highlight_text(self, text: str, query: str) -> str:
        """
        Highlight search terms in text using HTML <mark> tags.
        
        Args:
            text: Text to highlight
            query: Search query to highlight
            
        Returns:
            Text with <mark> tags around matches
        """
        if not text or not query:
            return text
        
        # Escape special regex characters in the query
        escaped_query = re.escape(query)
        
        # Case-insensitive replacement with <mark> tags
        pattern = re.compile(f'({escaped_query})', re.IGNORECASE)
        highlighted = pattern.sub(r'<mark>\1</mark>', text)
        
        return highlighted

