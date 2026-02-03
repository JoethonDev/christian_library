"""
Enhanced search functionality with Arabic text optimization.

Updates the existing search implementation to use the new Arabic cleaning pipeline
and optimized PostgreSQL features.
"""

from django.db.models import Q
from django.contrib.postgres.search import SearchQuery, SearchRank
from core.utils.arabic_text_processor import quick_arabic_normalize, TRIGRAM_SIMILARITY_THRESHOLD


def enhanced_arabic_search(queryset, query, content_type=None, use_fuzzy=True):
    """
    Enhanced Arabic search using the cleaning pipeline and PostgreSQL optimization.
    
    Args:
        queryset: Base ContentItem queryset
        query: Search query string
        content_type: Optional content type filter
        use_fuzzy: Whether to use trigram fuzzy matching
    
    Returns:
        Optimized search results with relevance ranking
    """
    if not query or not query.strip():
        return queryset.order_by('-created_at')
    
    # Normalize the search query for better matching
    normalized_query = quick_arabic_normalize(query.strip())
    
    # Apply content type filter if specified
    if content_type:
        queryset = queryset.filter(content_type=content_type)
    
    # Use different search strategies based on backend
    if 'postgresql' in queryset.db.settings_dict['ENGINE']:
        return _postgresql_arabic_search(queryset, query, normalized_query, use_fuzzy)
    else:
        return _fallback_arabic_search(queryset, query, normalized_query)


def _postgresql_arabic_search(queryset, original_query, normalized_query, use_fuzzy):
    """
    PostgreSQL-specific Arabic search with FTS and trigram matching.
    """
    # Create search query with Arabic configuration
    search_query = SearchQuery(normalized_query, config='arabic_optimized')
    
    # Primary FTS search on search_vector
    fts_results = queryset.filter(
        search_vector=search_query
    ).annotate(
        rank=SearchRank('search_vector', search_query)
    )
    
    if use_fuzzy and len(normalized_query) >= 3:
        # Add trigram similarity search for fuzzy matching
        from django.db import connection
        
        # Use custom Arabic similarity function if available
        similarity_condition = f"""
        (
            arabic_similarity(title_ar, %s) > {TRIGRAM_SIMILARITY_THRESHOLD} OR
            arabic_similarity(description_ar, %s) > {TRIGRAM_SIMILARITY_THRESHOLD} OR
            arabic_similarity(book_content, %s) > {TRIGRAM_SIMILARITY_THRESHOLD}
        )
        """
        
        fuzzy_results = queryset.extra(
            where=[similarity_condition],
            params=[normalized_query, normalized_query, normalized_query]
        ).annotate(
            similarity=connection.ops.sql_function(
                'GREATEST',
                connection.ops.sql_function('arabic_similarity', 'title_ar', normalized_query),
                connection.ops.sql_function('arabic_similarity', 'description_ar', normalized_query),
                connection.ops.sql_function('arabic_similarity', 'book_content', normalized_query)
            )
        )
        
        # Combine FTS and fuzzy results
        combined_results = fts_results.union(fuzzy_results).distinct()
        
        return combined_results.order_by('-rank', '-similarity', '-created_at')
    
    return fts_results.order_by('-rank', '-created_at')


def _fallback_arabic_search(queryset, original_query, normalized_query):
    """
    Fallback search for non-PostgreSQL databases (SQLite, etc.).
    """
    # Create search conditions for both original and normalized queries
    search_conditions = Q()
    
    # Search in Arabic fields with both queries
    for query_variant in [original_query, normalized_query]:
        if query_variant and query_variant.strip():
            search_conditions |= (
                Q(title_ar__icontains=query_variant) |
                Q(description_ar__icontains=query_variant) |
                Q(book_content__icontains=query_variant) |
                Q(tags__name_ar__icontains=query_variant)
            )
    
    # Also search English fields for multilingual support
    search_conditions |= (
        Q(title_en__icontains=original_query) |
        Q(description_en__icontains=original_query) |
        Q(tags__name_en__icontains=original_query)
    )
    
    return queryset.filter(search_conditions).distinct().order_by('-created_at')


# Integration with existing QuerySet
def update_contentitem_search_method():
    """
    Updates the ContentItemQuerySet.search_optimized method to use enhanced search.
    This should be applied as a monkey patch or integrated directly.
    """
    from apps.media_manager.models import ContentItemQuerySet
    
    def search_optimized_enhanced(self, query, content_type=None):
        """Enhanced search with Arabic text optimization"""
        return enhanced_arabic_search(self, query, content_type)
    
    # Replace the method
    ContentItemQuerySet.search_optimized = search_optimized_enhanced