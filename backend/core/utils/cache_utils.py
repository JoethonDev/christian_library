"""
Caching strategy and utilities for the Christian Library project.

This module provides:
1. Centralized cache key management
2. Template fragment caching utilities  
3. Per-view caching decorators
4. Cache invalidation utilities
5. Performance monitoring helpers
"""

from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.utils.translation import get_language
from functools import wraps
from typing import List, Dict, Any, Callable
import logging
import time

logger = logging.getLogger(__name__)


class CacheKeys:
    """Centralized cache key management"""
    
    # Content caching
    CONTENT_ITEM = "content_item_{id}_{lang}"
    CONTENT_LIST = "content_list_{type}_{page}_{lang}"
    CONTENT_STATS = "content_stats"
    CONTENT_SEARCH = "content_search_{query}_{type}_{lang}"
    
    # Course caching  
    COURSE_DETAIL = "course_detail_{id}_{lang}"
    COURSE_LIST = "course_list_{category}_{page}_{lang}"
    COURSE_MODULES = "course_modules_{course_id}_{include_content}_{lang}"
    COURSE_STATS = "course_stats_{id}"
    COURSE_CATEGORIES = "course_categories_{lang}"
    
    # User caching
    USER_STATS = "user_stats_{id}"
    USER_CONTENT_SUMMARY = "user_content_summary_{id}"
    CONTENT_MANAGERS = "content_managers"
    USER_LIST = "user_list"
    
    # Media processing
    MEDIA_PROCESSING_STATUS = "media_processing_status_{content_id}"
    MEDIA_CONVERSION_PROGRESS = "media_conversion_progress_{content_id}"
    
    # Navigation and UI
    NAVIGATION_MENU = "navigation_menu_{lang}"
    BREADCRUMBS = "breadcrumbs_{path}_{lang}"
    FEATURED_CONTENT = "featured_content_{lang}"
    
    # Search and filters
    SEARCH_SUGGESTIONS = "search_suggestions_{query}_{lang}"
    TAG_LIST = "tag_list_{popular}_{lang}"
    FILTER_OPTIONS = "filter_options_{type}_{lang}"
    
    @classmethod
    def get_content_cache_key(cls, content_id: int, lang: str = None) -> str:
        """Get cache key for content item"""
        lang = lang or get_language()
        return cls.CONTENT_ITEM.format(id=content_id, lang=lang)
    
    @classmethod
    def get_course_cache_key(cls, course_id: int, lang: str = None) -> str:
        """Get cache key for course detail"""
        lang = lang or get_language()
        return cls.COURSE_DETAIL.format(id=course_id, lang=lang)
    
    @classmethod
    def get_user_stats_key(cls, user_id: int) -> str:
        """Get cache key for user statistics"""
        return cls.USER_STATS.format(id=user_id)


class CacheConfig:
    """Cache configuration and timeouts"""
    
    # Timeout configurations (in seconds)
    TIMEOUTS = {
        'short': 300,      # 5 minutes - frequently changing data
        'medium': 1800,    # 30 minutes - moderate changes
        'long': 3600,      # 1 hour - stable data
        'very_long': 86400, # 24 hours - rarely changing data
    }
    
    # Cache timeout mapping for different types
    CONTENT_TIMEOUT = TIMEOUTS['medium']
    COURSE_TIMEOUT = TIMEOUTS['long']
    USER_TIMEOUT = TIMEOUTS['medium']
    NAVIGATION_TIMEOUT = TIMEOUTS['very_long']
    SEARCH_TIMEOUT = TIMEOUTS['short']
    STATS_TIMEOUT = TIMEOUTS['short']
    
    @classmethod
    def get_timeout(cls, cache_type: str) -> int:
        """Get appropriate timeout for cache type"""
        return getattr(cls, f'{cache_type.upper()}_TIMEOUT', cls.TIMEOUTS['medium'])


def cache_page_with_user(timeout: int = CacheConfig.CONTENT_TIMEOUT):
    """
    Cache decorator that includes user type in cache key.
    Different cache for authenticated vs anonymous users.
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Build cache key based on view, args, and user type
            user_type = 'auth' if request.user.is_authenticated else 'anon'
            lang = get_language()
            
            cache_key = f"view_{view_func.__name__}_{user_type}_{lang}_{hash(str(args) + str(sorted(request.GET.items())))}"
            
            # Try to get from cache
            response = cache.get(cache_key)
            if response is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return response
            
            # Generate response and cache it
            start_time = time.time()
            response = view_func(request, *args, **kwargs)
            generation_time = time.time() - start_time
            
            # Only cache successful responses
            if hasattr(response, 'status_code') and response.status_code == 200:
                cache.set(cache_key, response, timeout)
                logger.debug(f"Cache SET: {cache_key} (generated in {generation_time:.3f}s)")
            
            return response
        return wrapper
    return decorator


def cache_template_fragment(fragment_name: str, timeout: int = CacheConfig.CONTENT_TIMEOUT, vary_on: List[str] = None):
    """
    Utility for template fragment caching with automatic language variation
    """
    vary_on = vary_on or []
    lang = get_language()
    
    # Always include language in variation
    if 'lang' not in vary_on:
        vary_on.append(lang)
    
    cache_key = make_template_fragment_key(fragment_name, vary_on)
    
    def get_fragment():
        return cache.get(cache_key)
    
    def set_fragment(content):
        cache.set(cache_key, content, timeout)
        
    def delete_fragment():
        cache.delete(cache_key)
    
    return {
        'key': cache_key,
        'get': get_fragment,
        'set': set_fragment,
        'delete': delete_fragment
    }


class CacheInvalidator:
    """Handles cache invalidation when data changes"""
    
    @staticmethod
    def invalidate_content_caches(content_id: int = None):
        """Invalidate content-related caches"""
        keys_to_delete = [
            CacheKeys.CONTENT_STATS,
            CacheKeys.FEATURED_CONTENT.format(lang='ar'),
            CacheKeys.FEATURED_CONTENT.format(lang='en'),
        ]
        
        if content_id:
            keys_to_delete.extend([
                CacheKeys.get_content_cache_key(content_id, 'ar'),
                CacheKeys.get_content_cache_key(content_id, 'en'),
            ])
        
        # Delete content list caches (multiple pages and types)
        for content_type in ['video', 'audio', 'pdf', 'all']:
            for page in range(1, 6):  # Clear first 5 pages
                for lang in ['ar', 'en']:
                    keys_to_delete.append(
                        CacheKeys.CONTENT_LIST.format(type=content_type, page=page, lang=lang)
                    )
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} content cache keys")
    
    @staticmethod
    def invalidate_course_caches(course_id: int = None):
        """Invalidate course-related caches"""
        keys_to_delete = [
            CacheKeys.COURSE_CATEGORIES.format(lang='ar'),
            CacheKeys.COURSE_CATEGORIES.format(lang='en'),
        ]
        
        if course_id:
            keys_to_delete.extend([
                CacheKeys.get_course_cache_key(course_id, 'ar'),
                CacheKeys.get_course_cache_key(course_id, 'en'),
                CacheKeys.COURSE_STATS.format(id=course_id),
            ])
            
            # Clear course modules cache
            for include_content in [True, False]:
                for lang in ['ar', 'en']:
                    keys_to_delete.append(
                        CacheKeys.COURSE_MODULES.format(
                            course_id=course_id, 
                            include_content=include_content, 
                            lang=lang
                        )
                    )
        
        # Clear course list caches
        categories = ['theology', 'bible_study', 'history', 'apologetics', 'christian_living', 'liturgy', 'all']
        for category in categories:
            for page in range(1, 6):
                for lang in ['ar', 'en']:
                    keys_to_delete.append(
                        CacheKeys.COURSE_LIST.format(category=category, page=page, lang=lang)
                    )
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} course cache keys")
    
    @staticmethod
    def invalidate_user_caches(user_id: int = None):
        """Invalidate user-related caches"""
        keys_to_delete = [
            CacheKeys.CONTENT_MANAGERS,
            CacheKeys.USER_LIST,
        ]
        
        if user_id:
            keys_to_delete.extend([
                CacheKeys.get_user_stats_key(user_id),
                CacheKeys.USER_CONTENT_SUMMARY.format(id=user_id),
            ])
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} user cache keys")
    
    @staticmethod
    def invalidate_navigation_caches():
        """Invalidate navigation and UI caches"""
        keys_to_delete = [
            CacheKeys.NAVIGATION_MENU.format(lang='ar'),
            CacheKeys.NAVIGATION_MENU.format(lang='en'),
            CacheKeys.TAG_LIST.format(popular=True, lang='ar'),
            CacheKeys.TAG_LIST.format(popular=True, lang='en'),
            CacheKeys.TAG_LIST.format(popular=False, lang='ar'),
            CacheKeys.TAG_LIST.format(popular=False, lang='en'),
        ]
        
        cache.delete_many(keys_to_delete)
        logger.info(f"Invalidated {len(keys_to_delete)} navigation cache keys")
    
    @staticmethod
    def clear_all_caches():
        """Clear all application caches (use with caution)"""
        if hasattr(cache, 'clear'):
            cache.clear()
            logger.warning("Cleared ALL application caches")
        else:
            logger.error("Cache backend does not support clear() operation")


class CacheMonitor:
    """Monitor cache performance and statistics"""
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """Get cache statistics and performance metrics"""
        try:
            # This would depend on your cache backend
            # Redis example:
            if hasattr(cache, '_cache') and hasattr(cache._cache, 'get_client'):
                redis_client = cache._cache.get_client()
                info = redis_client.info('memory')
                
                return {
                    'backend': 'Redis',
                    'memory_used': info.get('used_memory_human'),
                    'memory_peak': info.get('used_memory_peak_human'),
                    'connected_clients': redis_client.info().get('connected_clients', 0),
                    'keyspace_hits': redis_client.info().get('keyspace_hits', 0),
                    'keyspace_misses': redis_client.info().get('keyspace_misses', 0),
                }
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
        
        return {
            'backend': 'Unknown',
            'status': 'Available' if cache._cache else 'Unavailable'
        }
    
    @staticmethod
    def warm_up_caches():
        """Pre-populate critical caches"""
        # from apps.courses.services import CourseService
        from apps.media_manager.services import ContentService
        
        try:
            logger.info("Starting cache warm-up...")
            
            # Course functionality has been removed
            # CourseService.get_active_courses()
            # CourseService.get_categories_with_counts()
            
            # Warm up recent content
            ContentService.get_recent_content(limit=20)
            ContentService.get_featured_content(limit=10)
            
            logger.info("Cache warm-up completed successfully")
            
        except Exception as e:
            logger.error(f"Error during cache warm-up: {str(e)}")


# Utility functions for use in views and templates
def get_cached_or_set(cache_key: str, callable_func: Callable, timeout: int = CacheConfig.CONTENT_TIMEOUT):
    """Get from cache or set with callable result"""
    result = cache.get(cache_key)
    if result is None:
        result = callable_func()
        cache.set(cache_key, result, timeout)
    return result


def cache_unless_authenticated(timeout: int = CacheConfig.CONTENT_TIMEOUT):
    """Cache view only for anonymous users"""
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Don't cache for authenticated users
            if request.user.is_authenticated:
                return view_func(request, *args, **kwargs)
            
            # Cache for anonymous users
            lang = get_language()
            cache_key = f"anon_view_{view_func.__name__}_{lang}_{hash(str(args) + str(sorted(request.GET.items())))}"
            
            response = cache.get(cache_key)
            if response is None:
                response = view_func(request, *args, **kwargs)
                if hasattr(response, 'status_code') and response.status_code == 200:
                    cache.set(cache_key, response, timeout)
            
            return response
        return wrapper
    return decorator