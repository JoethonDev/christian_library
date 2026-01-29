"""
Database health check and monitoring views for admin interface.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.http import JsonResponse
from django.db import connection
from django.conf import settings
from core.utils.database_optimization import QueryAnalyzer
import logging
import psutil
import os

logger = logging.getLogger(__name__)


@staff_member_required
def database_health_dashboard(request):
    """Database health dashboard for admin users"""
    context = {
        'title': 'Database Health Dashboard',
        'database_stats': _get_database_health_stats(),
        'connection_stats': _get_connection_stats(),
        'performance_metrics': _get_performance_metrics(),
        'optimization_suggestions': _get_optimization_suggestions(),
    }
    
    return render(request, 'admin/database_health.html', context)


@staff_member_required
def database_health_api(request):
    """API endpoint for database health data"""
    try:
        health_data = {
            'database_stats': _get_database_health_stats(),
            'connection_stats': _get_connection_stats(),
            'performance_metrics': _get_performance_metrics(),
            'query_analysis': _get_query_analysis(),
            'system_resources': _get_system_resources(),
        }
        
        return JsonResponse(health_data)
        
    except Exception as e:
        logger.error(f"Error getting database health data: {str(e)}")
        return JsonResponse({'error': 'Failed to retrieve health data'}, status=500)


def _get_database_health_stats():
    """Get basic database health statistics"""
    stats = {}
    
    try:
        with connection.cursor() as cursor:
            # Check database connection
            cursor.execute("SELECT 1")
            stats['connection_status'] = 'healthy'
            
            # Get database size (PostgreSQL specific)
            cursor.execute("""
                SELECT pg_size_pretty(pg_database_size(current_database())) as size
            """)
            result = cursor.fetchone()
            stats['database_size'] = result[0] if result else 'unknown'
            
            # Get table count
            cursor.execute("""
                SELECT count(*) FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            result = cursor.fetchone()
            stats['table_count'] = result[0] if result else 0
            
            # Get connection count
            cursor.execute("""
                SELECT count(*) FROM pg_stat_activity 
                WHERE datname = current_database()
            """)
            result = cursor.fetchone()
            stats['active_connections'] = result[0] if result else 0
            
            # Get long running queries
            cursor.execute("""
                SELECT count(*) FROM pg_stat_activity 
                WHERE datname = current_database() 
                AND state = 'active' 
                AND now() - query_start > interval '1 minute'
            """)
            result = cursor.fetchone()
            stats['long_running_queries'] = result[0] if result else 0
            
    except Exception as e:
        logger.error(f"Error getting database stats: {str(e)}")
        stats['connection_status'] = 'error'
        stats['error'] = str(e)
    
    return stats


def _get_connection_stats():
    """Get database connection statistics"""
    stats = {}
    
    try:
        with connection.cursor() as cursor:
            # Connection pool stats (if using connection pooling)
            cursor.execute("""
                SELECT 
                    count(*) as total_connections,
                    count(CASE WHEN state = 'active' THEN 1 END) as active,
                    count(CASE WHEN state = 'idle' THEN 1 END) as idle
                FROM pg_stat_activity 
                WHERE datname = current_database()
            """)
            result = cursor.fetchone()
            if result:
                stats['total_connections'] = result[0]
                stats['active_connections'] = result[1] 
                stats['idle_connections'] = result[2]
            
            # Average query time
            cursor.execute("""
                SELECT 
                    round(avg(total_time)::numeric, 2) as avg_query_time,
                    round(max(total_time)::numeric, 2) as max_query_time,
                    sum(calls) as total_queries
                FROM pg_stat_statements 
                WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                LIMIT 1
            """)
            result = cursor.fetchone()
            if result:
                stats['avg_query_time_ms'] = float(result[0]) if result[0] else 0
                stats['max_query_time_ms'] = float(result[1]) if result[1] else 0
                stats['total_queries'] = result[2] if result[2] else 0
            
    except Exception as e:
        # pg_stat_statements might not be available
        logger.warning(f"Could not get connection stats: {str(e)}")
        stats['error'] = 'pg_stat_statements extension not available'
    
    return stats


def _get_performance_metrics():
    """Get database performance metrics"""
    metrics = {}
    
    try:
        with connection.cursor() as cursor:
            # Cache hit ratio
            cursor.execute("""
                SELECT 
                    round(
                        (blks_hit::float / (blks_read + blks_hit + 1) * 100)::numeric, 
                        2
                    ) as cache_hit_ratio
                FROM pg_stat_database 
                WHERE datname = current_database()
            """)
            result = cursor.fetchone()
            metrics['cache_hit_ratio'] = float(result[0]) if result and result[0] else 0
            
            # Table statistics
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    n_tup_ins as inserts,
                    n_tup_upd as updates,
                    n_tup_del as deletes,
                    seq_scan,
                    seq_tup_read,
                    idx_scan,
                    idx_tup_fetch
                FROM pg_stat_user_tables 
                ORDER BY (n_tup_ins + n_tup_upd + n_tup_del) DESC 
                LIMIT 10
            """)
            metrics['top_tables'] = cursor.fetchall()
            
            # Index usage
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    idx_scan,
                    idx_tup_read,
                    idx_tup_fetch
                FROM pg_stat_user_indexes 
                WHERE idx_scan > 0
                ORDER BY idx_scan DESC 
                LIMIT 10
            """)
            metrics['top_indexes'] = cursor.fetchall()
            
    except Exception as e:
        logger.error(f"Error getting performance metrics: {str(e)}")
        metrics['error'] = str(e)
    
    return metrics


def _get_query_analysis():
    """Get query analysis from current request"""
    if not settings.DEBUG:
        return {'debug_mode': False}
    
    queries = connection.queries
    analysis = QueryAnalyzer.analyze_queries(queries)
    
    return {
        'debug_mode': True,
        'current_request_queries': len(queries),
        'total_time': analysis['total_time'],
        'average_time': analysis['average_time'],
        'issues_count': len(analysis['issues']),
        'issues': analysis['issues'][:10],  # Limit to first 10 issues
        'recommendations': analysis['recommendations']
    }


def _get_system_resources():
    """Get system resource usage"""
    try:
        process = psutil.Process(os.getpid())
        
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_usage': {
                'total': psutil.virtual_memory().total,
                'available': psutil.virtual_memory().available,
                'percent': psutil.virtual_memory().percent,
                'process_memory': process.memory_info().rss
            },
            'disk_usage': {
                'total': psutil.disk_usage('/').total,
                'free': psutil.disk_usage('/').free,
                'percent': psutil.disk_usage('/').percent
            } if os.name != 'nt' else None,
            'load_average': os.getloadavg() if hasattr(os, 'getloadavg') else None
        }
        
    except Exception as e:
        logger.error(f"Error getting system resources: {str(e)}")
        return {'error': str(e)}


def _get_optimization_suggestions():
    """Get database optimization suggestions"""
    suggestions = []
    
    try:
        # Check cache hit ratio
        cache_stats = _get_performance_metrics()
        if 'cache_hit_ratio' in cache_stats:
            hit_ratio = cache_stats['cache_hit_ratio']
            if hit_ratio < 95:
                suggestions.append({
                    'type': 'cache',
                    'priority': 'high' if hit_ratio < 90 else 'medium',
                    'message': f"Database cache hit ratio is {hit_ratio}%. Consider increasing shared_buffers."
                })
        
        # Check for tables without indexes
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT schemaname, tablename 
                FROM pg_stat_user_tables 
                WHERE seq_scan > 1000 AND seq_scan > idx_scan * 100
                LIMIT 5
            """)
            high_seq_scan_tables = cursor.fetchall()
            
            for table in high_seq_scan_tables:
                suggestions.append({
                    'type': 'index',
                    'priority': 'medium',
                    'message': f"Table {table[0]}.{table[1]} has high sequential scan ratio. Consider adding indexes."
                })
        
        # Check for unused indexes
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT schemaname, tablename, indexname 
                FROM pg_stat_user_indexes 
                WHERE idx_scan = 0 
                LIMIT 5
            """)
            unused_indexes = cursor.fetchall()
            
            for index in unused_indexes:
                suggestions.append({
                    'type': 'cleanup',
                    'priority': 'low',
                    'message': f"Index {index[2]} on {index[0]}.{index[1]} is unused and can be dropped."
                })
        
    except Exception as e:
        logger.error(f"Error generating optimization suggestions: {str(e)}")
        suggestions.append({
            'type': 'error',
            'priority': 'high',
            'message': f"Could not analyze database: {str(e)}"
        })
    
    return suggestions