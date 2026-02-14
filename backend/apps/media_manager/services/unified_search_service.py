"""
Unified Search Service - Centralized search logic for consistency across the application
Handles full-text search with dynamic sensitivity settings.
"""
import logging
from typing import List, Dict, Any, Optional
from django.db.models import Q, QuerySet, Case, When, Value, FloatField, F
from django.contrib.postgres.search import SearchQuery, SearchRank

from apps.media_manager.models import ContentItem
from apps.media_manager.services.search_settings_service import get_search_settings_service

logger = logging.getLogger(__name__)


class UnifiedSearchService:
    """
    Centralized search service that provides consistent search functionality
    across the entire application (frontend, admin, API).
    """
    
    def __init__(self):
        self.search_settings_service = get_search_settings_service()
    
    def search_content(
        self,
        query: str,
        content_type: Optional[str] = None,
        language: Optional[str] = None,
        use_dynamic_threshold: bool = True,
        override_threshold: Optional[float] = None
    ) -> QuerySet:
        """
        Perform unified search across all content types.
        
        Args:
            query: Search query string
            content_type: Optional filter by content type ('video', 'audio', 'pdf')
            language: Search language ('arabic' or 'english', auto-detected if None)
            use_dynamic_threshold: Whether to use admin-configured threshold (default: True)
            override_threshold: Override threshold for testing (default: None)
        
        Returns:
            QuerySet of ContentItem results ordered by relevance
        """
        from apps.media_manager.models import detect_query_language
        
        # Start with active content and proper relations
        qs = ContentItem.objects.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
        
        # Apply content type filter
        if content_type:
            qs = qs.filter(content_type=content_type)
        
        # If no query, return all active content sorted by date
        if not query:
            return qs.order_by('-created_at')
        
        # Detect language if not specified
        if language is None:
            lang_code = detect_query_language(query)
            language = 'arabic' if lang_code == 'ar' else 'english'
        
        # Get threshold (priority: override > dynamic > default)
        if override_threshold is not None:
            threshold = override_threshold
        elif use_dynamic_threshold:
            threshold = self.search_settings_service.get_current_threshold()
        else:
            threshold = 0.1  # Default fallback
        
        try:
            # Perform PostgreSQL full-text search
            return self._perform_fts_search(qs, query, language, threshold)
        except Exception as e:
            # Fallback to basic text search if PostgreSQL FTS unavailable
            logger.warning(f"FTS search failed, falling back to basic search: {e}")
            return self._perform_basic_search(qs, query)
    
    def _perform_fts_search(
        self,
        qs: QuerySet,
        query: str,
        language: str,
        threshold: float
    ) -> QuerySet:
        """
        Perform PostgreSQL full-text search with dynamic threshold.
        
        Args:
            qs: Base queryset
            query: Search query
            language: Search language configuration
            threshold: Minimum rank threshold
        
        Returns:
            QuerySet with search results ordered by rank
        """
        # Create search queries for both languages to support mixed content
        search_query_ar = SearchQuery(query, config='arabic')
        search_query_en = SearchQuery(query, config='english')
        
        # Use primary language query for ranking
        primary_query = search_query_ar if language == 'arabic' else search_query_en
        
        # Annotate with FTS rank
        qs = qs.annotate(
            rank=Case(
                # Items with search_vector get FTS ranking
                When(
                    search_vector__isnull=False,
                    then=SearchRank(F('search_vector'), primary_query)
                ),
                default=Value(0.0),
                output_field=FloatField()
            )
        )
        
        # Build comprehensive search conditions
        # FTS match OR text field matches (for items without search_vector)
        search_conditions = (
            Q(rank__gte=threshold) |  # FTS match with dynamic threshold
            Q(title_ar__icontains=query) |
            Q(title_en__icontains=query) |
            Q(description_ar__icontains=query) |
            Q(description_en__icontains=query) |
            Q(transcript__icontains=query) |
            Q(notes__icontains=query) |
            Q(tags__name_ar__icontains=query) |
            Q(tags__name_en__icontains=query)
        )
        
        # Apply filters and order by relevance
        return qs.filter(search_conditions).distinct().order_by('-rank', '-created_at')
    
    def _perform_basic_search(self, qs: QuerySet, query: str) -> QuerySet:
        """
        Fallback to basic text search (for non-PostgreSQL databases).
        
        Args:
            qs: Base queryset
            query: Search query
        
        Returns:
            QuerySet with search results
        """
        search_conditions = (
            Q(title_ar__icontains=query) |
            Q(title_en__icontains=query) |
            Q(description_ar__icontains=query) |
            Q(description_en__icontains=query) |
            Q(transcript__icontains=query) |
            Q(notes__icontains=query) |
            Q(tags__name_ar__icontains=query) |
            Q(tags__name_en__icontains=query)
        )
        return qs.filter(search_conditions).distinct().order_by('-created_at')
    
    def get_search_preview(
        self,
        query: str,
        threshold: float,
        content_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get search preview results for testing (used in admin dashboard).
        
        Args:
            query: Search query
            threshold: Test threshold value
            content_type: Optional content type filter
            limit: Maximum number of results
        
        Returns:
            List of result dictionaries with rank scores
        """
        # Use override threshold for testing
        results = self.search_content(
            query=query,
            content_type=content_type,
            use_dynamic_threshold=False,
            override_threshold=threshold
        )[:limit]
        
        # Format results with rank information
        formatted_results = []
        for item in results:
            formatted_results.append({
                'id': str(item.id),
                'title': item.title_ar or item.title_en,
                'type': item.content_type,
                'rank': float(getattr(item, 'rank', 0.0))
            })
        
        return formatted_results


# Singleton instance
_unified_search_service = None


def get_unified_search_service():
    """
    Get the singleton instance of UnifiedSearchService.
    
    Returns:
        UnifiedSearchService: Singleton service instance
    """
    global _unified_search_service
    if _unified_search_service is None:
        _unified_search_service = UnifiedSearchService()
    return _unified_search_service
