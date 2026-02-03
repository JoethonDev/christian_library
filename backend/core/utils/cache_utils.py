"""
Phase 4: Caching Implementation - Enhanced Utilities

This module provides comprehensive caching utilities for the Christian Library application,
implementing strategic caching for expensive queries identified in Phase 1-3.

REQUIRED: All cache operations MUST use explicit TTL values from TTL_* constants.
FORBIDDEN: No infinite or default TTLs, no per-user caching, no large binary blobs.

Cache Strategy:
- Statistics: Short-term caching for frequently accessed data
- Query results: Medium-term caching for expensive database operations
- Search results: Short-term caching for user-facing searches
- Content metadata: Medium-term caching for stable content data

Cache Keys Format (with namespace prefixes):
- cl:stats:content:v1 (Christian Library statistics)
- cl:query:related:{type}:{id}:v1 (query results)
- cl:search:{hash}:v1 (search results)
- cl:tags:popular:{limit}:v1 (popular tags)
"""

from django.core.cache import cache, caches
from django.core.cache.utils import make_template_fragment_key
from django.utils.translation import get_language
from functools import wraps
from typing import List, Dict, Any, Callable, Optional
import logging
import time
import hashlib
import json

logger = logging.getLogger(__name__)

# Cache TTL Constants - REQUIRED for all cache operations
class CacheTTL:
    """Named TTL constants for consistent cache timeout management"""
    # Statistics and aggregates (short-term, high churn)
    STATS_SHORT = 300      # 5 minutes - frequently changing statistics
    STATS_MEDIUM = 900     # 15 minutes - home page statistics
    STATS_LONG = 1800      # 30 minutes - admin dashboard statistics
    
    # Query results (medium-term, moderate churn)
    QUERY_SHORT = 600      # 10 minutes - search results
    QUERY_MEDIUM = 1800    # 30 minutes - related content, expensive queries
    QUERY_LONG = 3600      # 1 hour - stable content queries
    
    # Content metadata (longer-term, low churn)
    CONTENT_SHORT = 900    # 15 minutes - content lists
    CONTENT_MEDIUM = 3600  # 1 hour - popular tags, categories
    CONTENT_LONG = 14400   # 4 hours - navigation, rarely changing content
    
    # UI elements (long-term, very low churn)
    UI_MEDIUM = 3600       # 1 hour - navigation menus
    UI_LONG = 86400        # 24 hours - static UI elements

# Cache version for invalidation (Phase 4)
CACHE_VERSION = 1

# Namespace prefix for all cache keys (prevents collisions)
CACHE_NAMESPACE = 'cl'  # Christian Library


class CacheKeys:
    """Centralized cache key management with namespace prefixes
    
    All keys use the format: {CACHE_NAMESPACE}:{category}:{specific}:{version}
    This prevents key collisions and provides clear organization.
    """
    
    @staticmethod
    def _make_key(category: str, key: str) -> str:
        """Create namespaced cache key"""
        return f"{CACHE_NAMESPACE}:{category}:{key}:v{CACHE_VERSION}"
    
    # Content caching - HIGH VALUE: expensive queries, cross-view usage
    @staticmethod
    def content_stats() -> str:
        """Cache key for content statistics (admin dashboard)"""
        return CacheKeys._make_key('stats', 'content')
    
    @staticmethod 
    def home_stats() -> str:
        """Cache key for homepage statistics"""
        return CacheKeys._make_key('stats', 'home')
    
    @staticmethod
    def popular_tags(limit: int) -> str:
        """Cache key for popular tags list"""
        return CacheKeys._make_key('tags', f'popular_{limit}')
    
    @staticmethod
    def related_content(content_id: str, content_type: str) -> str:
        """Cache key for related content queries"""
        return CacheKeys._make_key('query', f'related_{content_type}_{content_id}')
    
    @staticmethod
    def search_results(query_hash: str) -> str:
        """Cache key for search results"""
        return CacheKeys._make_key('search', query_hash)


class CacheOperations:
    """High-value cache operations with explicit TTLs and comprehensive documentation
    
    REQUIRED: All operations must specify TTL from CacheTTL constants.
    FORBIDDEN: Generic caching, per-user caches, large binary objects.
    """
    
    @staticmethod
    def get_or_set_with_ttl(
        cache_key: str, 
        callable_func: Callable, 
        ttl: int, 
        cache_purpose: str
    ) -> Any:
        """Get from cache or set with callable result - REQUIRES explicit TTL
        
        Args:
            cache_key: Namespaced cache key
            callable_func: Function to call if cache miss
            ttl: Explicit TTL from CacheTTL constants
            cache_purpose: Human-readable purpose (for logging)
            
        Returns:
            Cached or computed result
        """
        result = cache.get(cache_key)
        if result is None:
            result = callable_func()
            cache.set(cache_key, result, ttl)
            logger.info(f"Cache SET: {cache_key} (purpose: {cache_purpose}, TTL: {ttl}s)")
        else:
            logger.debug(f"Cache HIT: {cache_key} (purpose: {cache_purpose})")
        return result
    
    @staticmethod
    def set_with_validation(cache_key: str, value: Any, ttl: int, purpose: str) -> None:
        """Set cache value with validation - prevents large object caching
        
        Args:
            cache_key: Namespaced cache key
            value: Value to cache (must be serializable and bounded)
            ttl: Explicit TTL from CacheTTL constants  
            purpose: Human-readable purpose (for logging)
        """
        # Validate cache value size (prevent memory bloat)
        try:
            serialized = json.dumps(value, default=str)
            if len(serialized) > 50000:  # 50KB limit
                logger.warning(f"Large cache value rejected for {cache_key}: {len(serialized)} bytes")
                return
        except (TypeError, ValueError):
            logger.warning(f"Non-serializable cache value rejected for {cache_key}")
            return
            
        cache.set(cache_key, value, ttl)
        logger.info(f"Cache SET: {cache_key} (purpose: {purpose}, TTL: {ttl}s)")
    
    @staticmethod
    def invalidate_pattern(pattern: str, reason: str) -> None:
        """Invalidate cache keys matching pattern
        
        Args:
            pattern: Cache key pattern to invalidate
            reason: Reason for invalidation (for logging)
        """
        # Note: Pattern-based deletion requires Redis backend
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(pattern)
                logger.info(f"Cache INVALIDATE: {pattern} (reason: {reason})")
            else:
                logger.warning(f"Pattern invalidation not supported for {pattern}")
        except Exception as e:
            logger.error(f"Cache invalidation error for {pattern}: {e}")


# DEPRECATED: Per-user caching violates caching guidelines
# Use whole-view caching with @cache_page decorator instead


# DEPRECATED: Generic template fragment caching removed
# Use Django's built-in {% cache %} template tag with explicit TTLs instead


class CacheInvalidation:
    """Simplified cache invalidation - keeps only high-value, necessary operations
    
    PRINCIPLE: Invalidate only what is actually cached and provides value.
    FORBIDDEN: Invalidating non-existent caches or over-granular invalidation.
    """
    
    @staticmethod
    def invalidate_content_stats(content_id: Optional[str] = None) -> None:
        """Invalidate content statistics when content changes
        
        PURPOSE: Keep admin dashboard and homepage stats accurate
        READ_FREQUENCY: High (dashboard, homepage)
        INVALIDATION: On content create/update/delete
        """
        keys_to_delete = [
            CacheKeys.content_stats(),
            CacheKeys.home_stats(),
        ]
        
        if content_id:
            # Invalidate related content cache for this specific item
            for content_type in ['video', 'audio', 'pdf']:
                keys_to_delete.append(
                    CacheKeys.related_content(content_id, content_type)
                )
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} content cache keys")
    
    @staticmethod 
    def invalidate_tag_caches() -> None:
        """Invalidate tag-related caches when tags change
        
        PURPOSE: Keep popular tags accurate
        READ_FREQUENCY: Moderate (homepage, search)
        INVALIDATION: On tag create/update/delete
        """
        keys_to_delete = [
            CacheKeys.popular_tags(8),  # Homepage popular tags
            CacheKeys.popular_tags(20), # Extended popular tags if used
            CacheKeys.home_stats(),     # Homepage includes tag counts
        ]
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} tag cache keys")
    
    @staticmethod
    def clear_all_application_caches() -> None:
        """Emergency cache clear - use with extreme caution
        
        PURPOSE: Recovery from cache corruption or major data changes
        USAGE: Should be rare, logs warning
        """
        if hasattr(cache, 'clear'):
            cache.clear()
            logger.warning("CLEARED ALL APPLICATION CACHES - this should be rare")
        else:
            logger.error("Cache backend does not support clear() operation")


class CacheMonitoring:
    """Essential cache monitoring - focuses on memory usage and hit rates only
    
    PURPOSE: Monitor cache effectiveness and prevent memory issues
    FORBIDDEN: Complex monitoring that adds overhead
    """
    
    @staticmethod
    def get_essential_stats() -> Dict[str, Any]:
        """Get essential cache statistics for monitoring
        
        Returns:
            Basic cache statistics: memory usage, hit rate
        """
        try:
            if hasattr(cache, '_cache') and hasattr(cache._cache, 'get_client'):
                redis_client = cache._cache.get_client()
                info = redis_client.info('memory')
                stats_info = redis_client.info('stats')
                
                hits = stats_info.get('keyspace_hits', 0)
                misses = stats_info.get('keyspace_misses', 0)
                hit_rate = (hits / (hits + misses) * 100) if (hits + misses) > 0 else 0
                
                return {
                    'backend': 'Redis',
                    'memory_used_mb': round(info.get('used_memory', 0) / 1024 / 1024, 2),
                    'memory_peak_mb': round(info.get('used_memory_peak', 0) / 1024 / 1024, 2),
                    'hit_rate_percent': round(hit_rate, 2),
                    'total_keys': redis_client.dbsize(),
                }
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
        
        return {'backend': 'Unknown', 'status': 'Error'}
    
    @staticmethod
    def warm_up_caches():
        """Warm up critical caches on application startup
        
        PURPOSE: Preload frequently accessed data to improve performance
        SCOPE: Only warm essential caches, avoid expensive operations
        """
        try:
            # Use global cache_invalidator to pre-populate critical caches
            logger.info("Warming up critical application caches")
            
            # Pre-populate home statistics cache if not exists
            if not cache_invalidator.get_home_statistics():
                # This would typically be populated by the actual view
                # For now, just log that cache warming was attempted
                logger.info("Home statistics cache will be populated on first request")
            
            # Pre-populate popular tags cache if not exists
            if not cache_invalidator.get_popular_tags():
                logger.info("Popular tags cache will be populated on first request")
            
            logger.info("Cache warm-up process completed")
            
        except Exception as e:
            logger.error(f"Error during cache warm-up: {str(e)}")


# DEPRECATED: Generic cache utilities removed to prevent cache abuse
# Use CacheOperations.get_or_set_with_ttl() with explicit TTL instead


# DEPRECATED: User-specific caching violates caching guidelines  
# Use whole-view caching with @cache_page decorator instead


# =====================================
# Phase 4: Enhanced Cache Manager - REFACTORED FOR SAFETY
# =====================================

class CacheInvalidator:
    """
    Enhanced cache manager for Phase 4 implementation - REFACTORED.
    
    FOCUS: Only high-value, read-heavy caches with explicit TTLs.
    REMOVED: Generic caching, per-user caches, over-granular operations.
    
    This class provides strategic caching for expensive queries identified in Phase 1-3.
    All operations use explicit TTLs from CacheTTL constants.
    """
    
    def __init__(self):
        # Use default cache - simplified from multiple cache backends
        self.cache = cache
    
    def _make_key(self, category: str, identifier: str) -> str:
        """Create consistent cache key with namespace and version"""
        return f"{CACHE_NAMESPACE}:{category}:{identifier}:v{CACHE_VERSION}"
    
    def _hash_query(self, query_params: Dict) -> str:
        """Create hash for complex query parameters"""
        query_str = json.dumps(query_params, sort_keys=True, default=str)
        return hashlib.md5(query_str.encode()).hexdigest()[:12]
    
    # Statistics Caching (HIGH VALUE: expensive aggregates, cross-view usage)
    def get_home_statistics(self) -> Optional[Dict]:
        """Get cached home page statistics
        
        PURPOSE: Avoid expensive COUNT queries on homepage
        READ_FREQUENCY: High (every homepage visit)
        TTL: 15 minutes (moderate churn, important freshness)
        """
        return self.cache.get(CacheKeys.home_stats())
    
    def set_home_statistics(self, stats: Dict) -> None:
        """Cache home page statistics with explicit TTL"""
        CacheOperations.set_with_validation(
            CacheKeys.home_stats(), 
            stats, 
            CacheTTL.STATS_MEDIUM,
            "homepage statistics"
        )
    
    def get_content_statistics(self) -> Optional[Dict]:
        """Get cached admin dashboard statistics
        
        PURPOSE: Avoid expensive admin dashboard queries
        READ_FREQUENCY: Moderate (admin usage)  
        TTL: 30 minutes (admin data, less critical freshness)
        """
        return self.cache.get(CacheKeys.content_stats())
    
    def set_content_statistics(self, stats: Dict) -> None:
        """Cache admin statistics with explicit TTL"""
        CacheOperations.set_with_validation(
            CacheKeys.content_stats(),
            stats,
            CacheTTL.STATS_LONG,
            "admin dashboard statistics"
        )
    
    # Query Results Caching (HIGH VALUE: expensive related content queries)
    def get_related_content(self, content_id: str, content_type: str) -> Optional[List]:
        """Get cached related content
        
        PURPOSE: Avoid expensive similarity/related content queries
        READ_FREQUENCY: High (content detail pages)
        TTL: 30 minutes (content relationships stable)
        """
        return self.cache.get(CacheKeys.related_content(content_id, content_type))
    
    def set_related_content(self, content_id: str, content_type: str, items: List) -> None:
        """Cache related content with explicit TTL"""
        CacheOperations.set_with_validation(
            CacheKeys.related_content(content_id, content_type),
            items,
            CacheTTL.QUERY_MEDIUM,
            f"related {content_type} content"
        )
    
    def get_popular_tags(self, limit: int = 8) -> Optional[List]:
        """Get cached popular tags
        
        PURPOSE: Avoid expensive tag counting queries
        READ_FREQUENCY: High (homepage, search pages)
        TTL: 1 hour (tags change slowly)
        """
        return self.cache.get(CacheKeys.popular_tags(limit))
    
    def set_popular_tags(self, tags: List, limit: int = 8) -> None:
        """Cache popular tags with explicit TTL"""
        CacheOperations.set_with_validation(
            CacheKeys.popular_tags(limit),
            tags,
            CacheTTL.CONTENT_MEDIUM,
            f"popular tags (limit: {limit})"
        )
    
    # Search Results Caching (MODERATE VALUE: user-facing searches)  
    def get_search_results(self, query: str, filters: Dict = None) -> Optional[Dict]:
        """Get cached search results
        
        PURPOSE: Avoid repeated expensive search queries
        READ_FREQUENCY: Moderate (search usage)
        TTL: 10 minutes (search results should be fresh)
        """
        query_data = {'query': query, 'filters': filters or {}}
        query_hash = self._hash_query(query_data)
        return self.cache.get(CacheKeys.search_results(query_hash))
    
    def set_search_results(self, query: str, filters: Dict, results: Dict) -> None:
        """Cache search results with explicit TTL"""
        query_data = {'query': query, 'filters': filters or {}}
        query_hash = self._hash_query(query_data)
        
        CacheOperations.set_with_validation(
            CacheKeys.search_results(query_hash),
            results,
            CacheTTL.QUERY_SHORT,
            f"search results for: {query[:50]}..."
        )
    
    # Cache Invalidation (SIMPLIFIED: only necessary operations)
    def invalidate_content_caches(self, content_type: Optional[str] = None) -> None:
        """Invalidate content-related caches when content changes
        
        SCOPE: Only invalidates actually cached data
        TRIGGER: Content create/update/delete operations
        """
        CacheInvalidation.invalidate_content_stats()
        logger.info(f"Invalidated content caches for type: {content_type or 'ALL'}")
    
    def invalidate_tag_caches(self) -> None:
        """Invalidate tag-related caches when tags change"""
        CacheInvalidation.invalidate_tag_caches()
        logger.info("Invalidated tag-related caches")
    
    def invalidate_navigation_caches(self) -> None:
        """Invalidate navigation-related caches when content structure changes"""
        # Clear navigation and menu-related caches
        CacheInvalidation.invalidate_content_stats()
        CacheInvalidation.invalidate_tag_caches()
        logger.info("Invalidated navigation-related caches")

    def get_cache_stats(self) -> Dict:
        """Get simplified cache performance statistics"""
        return CacheMonitoring.get_essential_stats()


def cache_unless_authenticated(timeout=300):
    """
    Conditional caching decorator - only caches responses for anonymous users.
    
    PURPOSE: Cache public pages for anonymous users while allowing 
             personalized content for authenticated users.
    USAGE: Decorator for views that serve different content based on auth status.
    
    Args:
        timeout: Cache timeout in seconds (default 5 minutes)
        
    Returns:
        Decorated function that conditionally caches based on authentication
    """
    from django.views.decorators.cache import cache_page
    from django.utils.decorators import decorator_from_middleware
    from django.middleware.cache import CacheMiddleware
    
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Only cache for anonymous users
            if not request.user.is_authenticated:
                # Use Django's built-in cache_page decorator for anonymous users
                cached_func = cache_page(timeout)(func)
                return cached_func(request, *args, **kwargs)
            else:
                # No caching for authenticated users - serve fresh content
                return func(request, *args, **kwargs)
        return wrapper
    return decorator


# Global Phase 4 cache manager instance
cache_invalidator = CacheInvalidator()