"""
Database optimization utilities for the Christian Library project.

This module provides:
1. Query optimization decorators and utilities
2. Database connection monitoring
3. Query performance logging
4. N+1 query detection and prevention
5. Database health checks
"""

from django.db import connection, connections
from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch, Q
from functools import wraps
from typing import Dict, List, Any, Optional, Callable
import logging
import time
import threading

logger = logging.getLogger('db_performance')


class QueryMonitor:
    """Monitor database queries for performance optimization"""
    
    _local = threading.local()
    
    @classmethod
    def start_monitoring(cls):
        """Start monitoring queries for current request"""
        cls._local.queries = []
        cls._local.start_time = time.time()
    
    @classmethod
    def log_query(cls, query: str, duration: float):
        """Log a query with its duration"""
        if hasattr(cls._local, 'queries'):
            cls._local.queries.append({
                'query': query,
                'duration': duration,
                'timestamp': time.time()
            })
    
    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Get query statistics for current request"""
        if not hasattr(cls._local, 'queries'):
            return {}
        
        queries = cls._local.queries
        total_time = sum(q['duration'] for q in queries)
        
        return {
            'query_count': len(queries),
            'total_time': total_time,
            'avg_time': total_time / len(queries) if queries else 0,
            'slow_queries': [q for q in queries if q['duration'] > 0.1],
            'request_time': time.time() - getattr(cls._local, 'start_time', 0)
        }
    
    @classmethod
    def reset(cls):
        """Reset monitoring for new request"""
        if hasattr(cls._local, 'queries'):
            delattr(cls._local, 'queries')
        if hasattr(cls._local, 'start_time'):
            delattr(cls._local, 'start_time')


def monitor_queries(func: Callable) -> Callable:
    """Decorator to monitor database queries in a function"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Record initial query count
        initial_queries = len(connection.queries)
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            
            # Calculate query statistics
            end_time = time.time()
            new_queries = connection.queries[initial_queries:]
            query_count = len(new_queries)
            total_query_time = sum(float(q['time']) for q in new_queries)
            
            # Log performance if above thresholds
            if query_count > 10 or total_query_time > 0.5:
                logger.warning(
                    f"Performance issue in {func.__name__}: "
                    f"{query_count} queries, {total_query_time:.3f}s DB time, "
                    f"{end_time - start_time:.3f}s total time"
                )
                
                # Log slow queries
                slow_queries = [q for q in new_queries if float(q['time']) > 0.1]
                for query in slow_queries:
                    logger.warning(f"Slow query ({query['time']}s): {query['sql'][:200]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            raise
    
    return wrapper


def optimize_queryset_for_model(model_class):
    """Get optimized queryset for a model with common select_related/prefetch_related"""
    
    optimization_config = {
        'ContentItem': {
            'select_related': ['module', 'module__course'],
            'prefetch_related': ['tags', 'videometa', 'audiometa', 'pdfmeta']
        },
        'Course': {
            'select_related': [],
            'prefetch_related': ['modules__contentitem_set']
        },
        'Module': {
            'select_related': ['course'],
            'prefetch_related': ['contentitem_set__tags']
        },
        'User': {
            'select_related': [],
            'prefetch_related': ['contentitem_set', 'course_set', 'module_set']
        }
    }
    
    model_name = model_class.__name__
    config = optimization_config.get(model_name, {})
    
    queryset = model_class.objects.all()
    
    if config.get('select_related'):
        queryset = queryset.select_related(*config['select_related'])
    
    if config.get('prefetch_related'):
        queryset = queryset.prefetch_related(*config['prefetch_related'])
    
    return queryset


class DatabaseHealthChecker:
    """Check database health and performance"""
    
    @staticmethod
    def check_connection_health() -> Dict[str, Any]:
        """Check database connection health"""
        try:
            # Test basic connectivity
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            # Get connection info
            db_settings = settings.DATABASES['default']
            
            return {
                'status': 'healthy',
                'engine': db_settings['ENGINE'],
                'name': db_settings['NAME'],
                'host': db_settings.get('HOST', 'localhost'),
                'port': db_settings.get('PORT', 'default')
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return {
                'status': 'unhealthy',
                'error': str(e)
            }
    
    @staticmethod
    def get_query_performance_stats() -> Dict[str, Any]:
        """Get query performance statistics"""
        try:
            with connection.cursor() as cursor:
                # PostgreSQL-specific queries
                if 'postgresql' in settings.DATABASES['default']['ENGINE']:
                    
                    # Get slow queries (if pg_stat_statements is available)
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_available_extensions 
                            WHERE name = 'pg_stat_statements' AND installed_version IS NOT NULL
                        )
                    """)
                    
                    has_pg_stat = cursor.fetchone()[0]
                    
                    if has_pg_stat:
                        cursor.execute("""
                            SELECT calls, total_time, mean_time, query
                            FROM pg_stat_statements
                            WHERE query NOT LIKE '%pg_stat_statements%'
                            ORDER BY mean_time DESC
                            LIMIT 5
                        """)
                        
                        slow_queries = cursor.fetchall()
                        
                        return {
                            'slow_queries': [
                                {
                                    'calls': row[0],
                                    'total_time': row[1],
                                    'mean_time': row[2],
                                    'query': row[3][:100] + '...'
                                } for row in slow_queries
                            ]
                        }
                
                # Generic database stats
                return {
                    'message': 'Performance statistics not available for this database engine'
                }
                
        except Exception as e:
            logger.error(f"Error getting query performance stats: {str(e)}")
            return {
                'error': str(e)
            }
    
    @staticmethod
    def check_table_sizes() -> Dict[str, Any]:
        """Check table sizes for monitoring"""
        try:
            with connection.cursor() as cursor:
                if 'postgresql' in settings.DATABASES['default']['ENGINE']:
                    cursor.execute("""
                        SELECT 
                            schemaname,
                            tablename,
                            attname,
                            n_distinct,
                            correlation
                        FROM pg_stats
                        WHERE schemaname = 'public'
                        AND tablename IN (
                            'media_manager_contentitem',
                            'courses_course', 
                            'courses_module',
                            'auth_user'
                        )
                        ORDER BY tablename, attname;
                    """)
                    
                    stats = cursor.fetchall()
                    
                    return {
                        'table_stats': [
                            {
                                'schema': row[0],
                                'table': row[1], 
                                'column': row[2],
                                'distinct_values': row[3],
                                'correlation': row[4]
                            } for row in stats
                        ]
                    }
                else:
                    return {'message': 'Table size checking not implemented for this database'}
                    
        except Exception as e:
            logger.error(f"Error checking table sizes: {str(e)}")
            return {'error': str(e)}


class QueryOptimizer:
    """Utilities for query optimization"""
    
    @staticmethod
    def get_optimized_content_queryset(filters: Dict[str, Any] = None):
        """Get optimized queryset for content items"""
        from apps.media_manager.models import ContentItem
        
        queryset = ContentItem.objects.select_related(
            'module',
            'module__course'
        ).prefetch_related(
            'tags',
            Prefetch('videometa'),
            Prefetch('audiometa'), 
            Prefetch('pdfmeta')
        ).filter(is_active=True)
        
        if filters:
            if filters.get('content_type'):
                queryset = queryset.filter(content_type=filters['content_type'])
            
            if filters.get('course_id'):
                queryset = queryset.filter(module__course_id=filters['course_id'])
            
            if filters.get('search'):
                search_term = filters['search']
                queryset = queryset.filter(
                    Q(title_ar__icontains=search_term) |
                    Q(title_en__icontains=search_term) |
                    Q(description_ar__icontains=search_term) |
                    Q(description_en__icontains=search_term)
                )
        
        return queryset
    
    # @staticmethod
    # def get_optimized_course_queryset(with_content: bool = False):
    #     """Get optimized queryset for courses"""
    #     # Course functionality has been removed
    #     return None
                        is_active=True
                    ).prefetch_related('contentitem_set__tags')
                )
            )
        else:
            queryset = queryset.prefetch_related('modules')
        
        return queryset
    
    @staticmethod
    def optimize_media_processing_queries():
        """Get optimized queries for media processing status"""
        from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta
        
        # Get items that need processing
        pending_videos = VideoMeta.objects.filter(
            processing_status__in=['pending', 'processing']
        ).select_related('content_item')
        
        pending_audio = AudioMeta.objects.filter(
            processing_status__in=['pending', 'processing'] 
        ).select_related('content_item')
        
        pending_pdfs = PdfMeta.objects.filter(
            processing_status__in=['pending', 'processing']
        ).select_related('content_item')
        
        return {
            'videos': pending_videos,
            'audio': pending_audio,
            'pdfs': pending_pdfs
        }


def cache_query_result(cache_key: str, timeout: int = 3600):
    """Decorator to cache query results"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Try to get from cache first
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            # Execute query and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            
            return result
        return wrapper
    return decorator


# Connection pool monitoring
def get_connection_pool_stats() -> Dict[str, Any]:
    """Get database connection pool statistics"""
    try:
        stats = {}
        for alias in connections:
            connection = connections[alias]
            
            # Basic connection info
            stats[alias] = {
                'vendor': getattr(connection, 'vendor', 'unknown'),
                'queries_count': len(getattr(connection, 'queries', [])),
                'is_usable': connection.is_usable() if hasattr(connection, 'is_usable') else True
            }
            
            # PostgreSQL specific stats
            if hasattr(connection, 'connection') and connection.connection:
                try:
                    stats[alias]['server_version'] = getattr(
                        connection.connection, 'server_version', 'unknown'
                    )
                except:
                    pass
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting connection pool stats: {str(e)}")
        return {'error': str(e)}