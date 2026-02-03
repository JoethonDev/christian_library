"""
Unified Content Service for Frontend API
Centralizes all business logic and eliminates duplicated code across views.
Handles language processing, meta attachment, and content retrieval with zero N+1 queries.
"""
from typing import Dict, List, Optional, Tuple, Any
from django.utils.translation import get_language
from django.core.paginator import Paginator
from django.db.models import QuerySet
from apps.media_manager.models import ContentItem, Tag


class ContentLanguageProcessor:
    """Handles all language-related processing for content items and tags"""
    
    @staticmethod
    def process_content_item(item: ContentItem, language: str = None) -> ContentItem:
        """Process a single content item with language preferences and meta attachment"""
        if not language:
            language = get_language()
        
        # Set language-aware properties
        item.title = item.get_title(language)
        item.description = item.get_description(language)
        
        # Attach meta object for template access (prevents lazy loading)
        if item.content_type == 'video' and hasattr(item, 'videometa') and item.videometa:
            item.meta = item.videometa
        elif item.content_type == 'audio' and hasattr(item, 'audiometa') and item.audiometa:
            item.meta = item.audiometa
        elif item.content_type == 'pdf' and hasattr(item, 'pdfmeta') and item.pdfmeta:
            item.meta = item.pdfmeta
        else:
            item.meta = None
        
        return item
    
    @staticmethod
    def process_content_list(items: QuerySet, language: str = None) -> List[ContentItem]:
        """Process a list of content items efficiently in memory"""
        if not language:
            language = get_language()
        
        processed_items = []
        for item in items:
            processed_items.append(
                ContentLanguageProcessor.process_content_item(item, language)
            )
        return processed_items
    
    @staticmethod
    def process_tag(tag: Tag, language: str = None) -> Tag:
        """Process a single tag with language preferences"""
        if not language:
            language = get_language()
        
        tag.name = tag.get_name(language)
        return tag
    
    @staticmethod
    def process_tag_list(tags: QuerySet, language: str = None) -> List[Tag]:
        """Process a list of tags efficiently in memory"""
        if not language:
            language = get_language()
        
        processed_tags = []
        for tag in tags:
            processed_tags.append(
                ContentLanguageProcessor.process_tag(tag, language)
            )
        return processed_tags


class ContentService:
    """Unified service for all content operations"""
    
    def __init__(self):
        self.language_processor = ContentLanguageProcessor()
    
    def get_home_page_data(self) -> Dict[str, Any]:
        """Get all home page data with minimal database queries (2-3 total)"""
        # Query 1: Get all content statistics in single query
        stats = ContentItem.objects.get_statistics()
        
        # Query 2: Get home content in single optimized query
        home_data = ContentItem.objects.get_home_data()
        
        # Query 3: Get popular tags with content count (if not cached)
        popular_tags = Tag.objects.popular(limit=8)
        
        # Process in memory - zero additional queries
        current_language = get_language()
        
        return {
            'latest_videos': self.language_processor.process_content_list(
                home_data['videos'], current_language
            ),
            'latest_audios': self.language_processor.process_content_list(
                home_data['audios'], current_language  
            ),
            'latest_pdfs': self.language_processor.process_content_list(
                home_data['pdfs'], current_language
            ),
            'popular_tags': self.language_processor.process_tag_list(
                popular_tags, current_language
            ),
            'stats': stats
        }
    
    def get_content_listing(
        self, 
        content_type: str, 
        search_query: str = '', 
        tag_filter: str = '',
        page: int = 1,
        per_page: int = 12
    ) -> Dict[str, Any]:
        """Get paginated content listing with filtering - optimized queries"""
        current_language = get_language()
        
        # Single optimized query with all relations
        if search_query:
            content_qs = ContentItem.objects.search_optimized(search_query, content_type)
        else:
            content_qs = ContentItem.objects.for_listing(content_type)
        
        # Apply tag filter if provided
        if tag_filter:
            content_qs = content_qs.filter(tags__id=tag_filter)
        
        # Pagination
        paginator = Paginator(content_qs, per_page)
        content_page = paginator.get_page(page)
        
        # Process content items
        processed_content = self.language_processor.process_content_list(
            content_page, current_language
        )
        
        # Get available tags for filter - single query
        available_tags = Tag.objects.for_content_type(content_type)
        processed_tags = self.language_processor.process_tag_list(
            available_tags, current_language
        )
        
        return {
            'content': processed_content,
            'available_tags': processed_tags,
            'pagination': {
                'page': content_page,
                'total_count': paginator.count,
                'num_pages': paginator.num_pages,
                'has_previous': content_page.has_previous(),
                'has_next': content_page.has_next(),
            }
        }
    
    def get_content_detail(self, content_id: str, content_type: str, user=None) -> Dict[str, Any]:
        """Get content detail with related content - minimal queries"""
        from django.shortcuts import get_object_or_404
        from django.http import Http404
        current_language = get_language()
        
        # Query 1: Get main content with all relations
        content = get_object_or_404(
            ContentItem.objects.select_related(
                'videometa', 'audiometa', 'pdfmeta'
            ).prefetch_related('tags'),
            id=content_id,
            content_type=content_type
        )
        
        # Visibility check: if not active, only permit for staff
        if not content.is_active and (user is None or not user.is_staff):
            raise Http404("Content is not active")
        
        # Query 2: Get related content using optimized method
        related_content = ContentItem.objects.related_content(content)
        
        # Process in memory
        processed_content = self.language_processor.process_content_item(content, current_language)
        processed_related = self.language_processor.process_content_list(
            related_content, current_language
        )
        
        return {
            'content': processed_content,
            'related_content': processed_related
        }
    
    def get_tag_content(
        self, 
        tag_id: str, 
        content_type_filter: str = '',
        page: int = 1,
        per_page: int = 12
    ) -> Dict[str, Any]:
        """Get content by tag with statistics - optimized queries"""
        from django.shortcuts import get_object_or_404
        current_language = get_language()
        
        # Query 1: Get tag with statistics in single query
        tag_with_stats = Tag.objects.get_tag_statistics(tag_id)
        if not tag_with_stats:
            raise get_object_or_404(Tag, id=tag_id, is_active=True)
        
        # Query 2: Get content for this tag
        content_qs = ContentItem.objects.active().filter(
            tags=tag_with_stats
        ).select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').order_by('-created_at')
        
        # Apply content type filter
        if content_type_filter in ['video', 'audio', 'pdf']:
            content_qs = content_qs.filter(content_type=content_type_filter)
        
        # Pagination
        paginator = Paginator(content_qs, per_page)
        content_page = paginator.get_page(page)
        
        # Process in memory
        processed_tag = self.language_processor.process_tag(tag_with_stats, current_language)
        processed_content = self.language_processor.process_content_list(
            content_page, current_language
        )
        
        return {
            'tag': processed_tag,
            'content': processed_content,
            'tag_stats': {
                'total_videos': tag_with_stats.total_videos,
                'total_audios': tag_with_stats.total_audios,
                'total_pdfs': tag_with_stats.total_pdfs,
                'total_content': tag_with_stats.total_content
            },
            'pagination': {
                'page': content_page,
                'total_count': paginator.count,
                'num_pages': paginator.num_pages,
                'has_previous': content_page.has_previous(),
                'has_next': content_page.has_next(),
            }
        }
    
    def get_search_results(
        self,
        search_query: str,
        content_type_filter: str = '',
        tag_filter: str = '',
        sort_by: str = '-created_at',
        page: int = 1,
        per_page: int = 12
    ) -> Dict[str, Any]:
        """Unified search with all filters - optimized queries"""
        current_language = get_language()
        
        if not any([search_query, content_type_filter, tag_filter]):
            return {
                'results': [],
                'available_tags': [],
                'pagination': None,
                'total_count': 0
            }
        
        # Single optimized search query
        results_qs = ContentItem.objects.search_optimized(search_query, content_type_filter)
        
        # Apply tag filter if specified
        if tag_filter:
            results_qs = results_qs.filter(tags__id=tag_filter)
        
        # Apply sorting (if not using FTS ranking)
        if sort_by in ['title_ar', 'title_en'] or (not search_query or content_type_filter != 'pdf'):
            if sort_by in ['title_ar', 'title_en']:
                results_qs = results_qs.order_by(sort_by)
            else:
                results_qs = results_qs.order_by('-created_at')
        
        # Pagination
        paginator = Paginator(results_qs, per_page)
        results_page = paginator.get_page(page)
        
        # Get available tags for filters
        available_tags = Tag.objects.active().order_by('name_ar')
        
        # Process in memory
        processed_results = self.language_processor.process_content_list(
            results_page, current_language
        )
        processed_tags = self.language_processor.process_tag_list(
            available_tags, current_language
        )
        
        return {
            'results': processed_results,
            'available_tags': processed_tags,
            'pagination': {
                'page': results_page,
                'total_count': paginator.count,
                'num_pages': paginator.num_pages,
                'has_previous': results_page.has_previous(),
                'has_next': results_page.has_next(),
            },
            'total_count': paginator.count
        }
    
    def get_autocomplete_suggestions(self, query: str) -> List[str]:
        """Get autocomplete suggestions from both content and tags - optimized"""
        if len(query) < 2:
            return []
        
        current_language = get_language()
        suggestions = []
        
        # Get content title suggestions (single query)
        content_titles = ContentItem.objects.for_autocomplete(query, current_language)
        for title_ar, title_en in content_titles:
            if current_language == 'ar':
                title = title_ar or title_en
            else:
                title = title_en or title_ar
            
            if title and title not in suggestions:
                suggestions.append(title)
        
        # Get tag name suggestions (single query) 
        tag_names = Tag.objects.for_autocomplete(query, current_language)
        for name_ar, name_en in tag_names:
            if current_language == 'ar':
                name = name_ar or name_en
            else:
                name = name_en or name_ar
            
            if name and name not in suggestions:
                suggestions.append(name)
        
        return suggestions[:10]


class APIService:
    """Service for API endpoints with optimized serialization"""
    
    def __init__(self):
        self.content_service = ContentService()
        self.language_processor = ContentLanguageProcessor()
    
    def get_home_api_data(self) -> Dict[str, Any]:
        """Get home page data formatted for API response"""
        home_data = self.content_service.get_home_page_data()
        current_language = get_language()
        
        def format_content_item(item):
            """Format content item for API"""
            base_data = {
                'id': str(item.id),
                'title': item.title,
                'description': item.description,
                'tags': [tag.get_name(current_language) for tag in item.tags.all()],
                'created_at': item.created_at.isoformat(),
            }
            
            # Add type-specific metadata
            if item.content_type == 'video' and item.meta:
                base_data['thumbnail_url'] = getattr(item.meta, 'thumbnail_url', None)
            elif item.content_type == 'audio' and item.meta:
                base_data['duration'] = getattr(item.meta, 'duration_seconds', None)
            elif item.content_type == 'pdf' and item.meta:
                base_data['page_count'] = getattr(item.meta, 'page_count', None)
            
            return base_data
        
        return {
            'featured_videos': [format_content_item(item) for item in home_data['latest_videos']],
            'featured_audios': [format_content_item(item) for item in home_data['latest_audios']],
            'featured_pdfs': [format_content_item(item) for item in home_data['latest_pdfs']],
            'statistics': home_data['stats']
        }
    
    def get_search_api_data(
        self, 
        query: str, 
        content_type: str = 'all', 
        language: str = None
    ) -> Dict[str, Any]:
        """Get search results formatted for API response"""
        if not language:
            language = get_language()
        
        if not query:
            return {'tags': [], 'content': []}
        
        # Get search results using content service
        content_results = self.content_service.get_search_results(
            search_query=query,
            content_type_filter=content_type if content_type != 'all' else '',
            per_page=20
        )
        
        # Get tag results
        tag_results = Tag.objects.for_autocomplete(query, language)
        
        def format_content_item(item):
            return {
                'id': str(item.id),
                'title': item.title,
                'description': item.description,
                'type': item.content_type,
                'tags': [tag.get_name(language) for tag in item.tags.all()],
            }
        
        def format_tag(name_ar, name_en):
            name = name_ar if language == 'ar' else (name_en or name_ar)
            # Get tag object for additional data
            try:
                tag = Tag.objects.get(name_ar=name_ar) if name_ar else Tag.objects.get(name_en=name_en)
                return {
                    'id': str(tag.id),
                    'name': name,
                    'description': tag.description_ar,
                    'color': tag.color,
                    'type': 'tag',
                }
            except Tag.DoesNotExist:
                return None
        
        formatted_tags = []
        for name_ar, name_en in tag_results:
            formatted_tag = format_tag(name_ar, name_en)
            if formatted_tag:
                formatted_tags.append(formatted_tag)
        
        return {
            'tags': formatted_tags[:10],
            'content': [format_content_item(item) for item in content_results['results']]
        }
    
    def get_statistics_api_data(self) -> Dict[str, Any]:
        """Get content statistics formatted for API response"""
        # Single query for all stats
        content_stats = ContentItem.objects.get_statistics()
        
        # Add tag count (separate query)
        tag_count = Tag.objects.active().count()
        content_stats['total_tags'] = tag_count
        
        # Get content by tag data
        popular_tags_with_content = Tag.objects.popular(limit=10)
        current_language = get_language()
        
        content_by_tag = []
        for tag in popular_tags_with_content:
            content_by_tag.append({
                'tag': tag.get_name(current_language),
                'content_count': tag.content_count,
                'color': tag.color
            })
        
        content_stats['content_by_tag'] = content_by_tag
        
        return content_stats