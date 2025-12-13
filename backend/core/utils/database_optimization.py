"""
Database optimization decorators and query analysis utilities.
"""

import functools
import time
import logging
from django.db import connection, reset_queries
from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch
from typing import Any, Callable, List, Dict
import json

logger = logging.getLogger(__name__)


class QueryAnalyzer:
    """Analyze database queries for optimization opportunities"""
    
    @staticmethod
    def analyze_queries(queries: List[Dict]) -> Dict[str, Any]:
        """Analyze a list of queries for performance issues"""
        if not queries:
            return {'total_queries': 0, 'total_time': 0, 'issues': []}
        
        total_time = sum(float(q.get('time', 0)) for q in queries)
        total_queries = len(queries)
        
        issues = []
        
        # Check for N+1 queries
        query_patterns = {}
        for query in queries:
            sql = query.get('sql', '').strip()
            pattern = QueryAnalyzer._extract_pattern(sql)
            query_patterns[pattern] = query_patterns.get(pattern, 0) + 1
        
        for pattern, count in query_patterns.items():
            if count > 3:
                issues.append({
                    'type': 'n_plus_one',
                    'pattern': pattern,
                    'count': count,
                    'severity': 'high' if count > 10 else 'medium'
                })
        
        # Check for slow queries
        slow_queries = [q for q in queries if float(q.get('time', 0)) > 0.1]
        for query in slow_queries:
            issues.append({
                'type': 'slow_query',
                'sql': query.get('sql', ''),
                'time': float(query.get('time', 0)),
                'severity': 'high' if float(query.get('time', 0)) > 0.5 else 'medium'
            })
        
        # Check for missing indexes (basic heuristics)
        for query in queries:
            sql = query.get('sql', '').lower()
            if 'where' in sql and 'index' not in sql and float(query.get('time', 0)) > 0.05:
                issues.append({
                    'type': 'potential_missing_index',
                    'sql': query.get('sql', ''),
                    'time': float(query.get('time', 0)),
                    'severity': 'medium'
                })
        
        return {
            'total_queries': total_queries,
            'total_time': total_time,
            'average_time': total_time / total_queries if total_queries > 0 else 0,
            'slow_queries_count': len(slow_queries),
            'issues': issues,
            'recommendations': QueryAnalyzer._generate_recommendations(issues)
        }
    
    @staticmethod
    def _extract_pattern(sql: str) -> str:
        """Extract a pattern from SQL for duplicate detection"""
        import re
        
        # Normalize SQL
        sql_lower = sql.lower().strip()
        
        # Replace specific values with placeholders
        pattern = re.sub(r"'[^']*'", "'?'", sql_lower)
        pattern = re.sub(r'"[^"]*"', '"?"', pattern)
        pattern = re.sub(r'\b\d+\b', '?', pattern)
        pattern = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '?', pattern)
        
        return pattern[:100]  # Truncate for readability
    
    @staticmethod
    def _generate_recommendations(issues: List[Dict]) -> List[str]:
        """Generate optimization recommendations based on issues"""
        recommendations = []
        
        n_plus_one_count = len([i for i in issues if i['type'] == 'n_plus_one'])
        slow_query_count = len([i for i in issues if i['type'] == 'slow_query'])
        missing_index_count = len([i for i in issues if i['type'] == 'potential_missing_index'])
        
        if n_plus_one_count > 0:
            recommendations.append(
                f"Consider using select_related() or prefetch_related() to reduce {n_plus_one_count} N+1 query issues"
            )
        
        if slow_query_count > 0:
            recommendations.append(
                f"Optimize {slow_query_count} slow queries by adding indexes or reducing complexity"
            )
        
        if missing_index_count > 0:
            recommendations.append(
                f"Consider adding database indexes for {missing_index_count} potentially unindexed queries"
            )
        
        return recommendations


def query_debugger(func: Callable) -> Callable:
    """Decorator to debug and analyze database queries"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not settings.DEBUG:
            return func(*args, **kwargs)
        
        # Reset queries and start monitoring
        reset_queries()
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            
            # Analyze queries
            queries = connection.queries
            analysis = QueryAnalyzer.analyze_queries(queries)
            
            if analysis['issues']:
                logger.warning(
                    f"Query issues in {func.__name__}: "
                    f"{analysis['total_queries']} queries, "
                    f"{analysis['total_time']:.3f}s total, "
                    f"{len(analysis['issues'])} issues found"
                )
                
                for issue in analysis['issues']:
                    if issue['severity'] == 'high':
                        logger.warning(f"High severity {issue['type']}: {issue}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            raise
    
    return wrapper


def optimize_queries(select_related: List[str] = None, prefetch_related: List[str] = None):
    """Decorator to automatically optimize QuerySet with select_related and prefetch_related"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # This decorator would be applied to view methods
            # The actual optimization would depend on the specific QuerySet usage
            result = func(*args, **kwargs)
            
            # If result is a QuerySet, apply optimizations
            if hasattr(result, 'select_related') and select_related:
                result = result.select_related(*select_related)
            
            if hasattr(result, 'prefetch_related') and prefetch_related:
                result = result.prefetch_related(*prefetch_related)
            
            return result
        
        return wrapper
    return decorator


def cache_query_result(cache_key_prefix: str, timeout: int = 300, vary_on: List[str] = None):
    """Decorator to cache database query results"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key
            cache_key_parts = [cache_key_prefix]
            
            if vary_on:
                for vary_key in vary_on:
                    if vary_key in kwargs:
                        cache_key_parts.append(f"{vary_key}_{kwargs[vary_key]}")
            
            cache_key = "_".join(str(part) for part in cache_key_parts)
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            
            # Only cache serializable results
            try:
                cache.set(cache_key, result, timeout)
                logger.debug(f"Cached result for {cache_key}")
            except Exception as e:
                logger.warning(f"Failed to cache result for {cache_key}: {str(e)}")
            
            return result
        
        return wrapper
    return decorator


class DatabaseOptimizer:
    """Tools for database optimization and monitoring"""
    
    @staticmethod
    def get_slow_queries(threshold_ms: float = 100) -> List[Dict]:
        """Get slow queries from the current request"""
        if not settings.DEBUG:
            return []
        
        slow_queries = []
        for query in connection.queries:
            time_ms = float(query.get('time', 0)) * 1000
            if time_ms > threshold_ms:
                slow_queries.append({
                    'sql': query.get('sql', ''),
                    'time_ms': time_ms,
                    'analysis': QueryAnalyzer._extract_pattern(query.get('sql', ''))
                })
        
        return slow_queries
    
    @staticmethod
    def analyze_table_usage() -> Dict[str, Any]:
        """Analyze table usage patterns"""
        if not settings.DEBUG:
            return {}
        
        table_queries = {}
        for query in connection.queries:
            sql = query.get('sql', '').lower()
            
            # Extract table names (basic regex)
            import re
            tables = re.findall(r'from\s+["`]?(\w+)["`]?', sql)
            tables.extend(re.findall(r'join\s+["`]?(\w+)["`]?', sql))
            
            for table in tables:
                if table not in table_queries:
                    table_queries[table] = {'count': 0, 'total_time': 0}
                
                table_queries[table]['count'] += 1
                table_queries[table]['total_time'] += float(query.get('time', 0))
        
        return table_queries
    
    @staticmethod
    def generate_index_suggestions() -> List[Dict]:
        """Generate database index suggestions based on query patterns"""
        suggestions = []
        
        if not settings.DEBUG:
            return suggestions
        
        # Analyze WHERE clauses for potential indexes
        for query in connection.queries:
            sql = query.get('sql', '')
            time_ms = float(query.get('time', 0)) * 1000
            
            if time_ms > 50:  # Only suggest indexes for slower queries
                import re
                
                # Look for WHERE clauses
                where_matches = re.findall(r'WHERE\s+([^ORDER|GROUP|HAVING|LIMIT]+)', sql.upper())
                for where_clause in where_matches:
                    # Extract column names (very basic)
                    columns = re.findall(r'(\w+)\s*[=<>]', where_clause)
                    if columns:
                        suggestions.append({
                            'type': 'composite_index',
                            'columns': columns[:3],  # Max 3 columns for composite index
                            'query_time_ms': time_ms,
                            'reason': 'WHERE clause optimization'
                        })
        
        return suggestions
    
    @staticmethod
    def get_database_stats() -> Dict[str, Any]:
        """Get comprehensive database statistics"""
        stats = {
            'connection_queries': len(connection.queries),
            'total_query_time': sum(float(q.get('time', 0)) for q in connection.queries),
            'slow_queries': len(DatabaseOptimizer.get_slow_queries()),
            'table_usage': DatabaseOptimizer.analyze_table_usage(),
        }
        
        if stats['connection_queries'] > 0:
            stats['average_query_time'] = stats['total_query_time'] / stats['connection_queries']
        
        return stats


# Context manager for query monitoring
class QueryMonitor:
    """Context manager for monitoring queries in a code block"""
    
    def __init__(self, name: str = "QueryMonitor"):
        self.name = name
        self.start_queries = 0
        self.start_time = 0
    
    def __enter__(self):
        if settings.DEBUG:
            self.start_queries = len(connection.queries)
            self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if settings.DEBUG:
            end_time = time.time()
            total_time = end_time - self.start_time
            new_queries = connection.queries[self.start_queries:]
            
            if new_queries:
                analysis = QueryAnalyzer.analyze_queries(new_queries)
                logger.debug(
                    f"{self.name}: {len(new_queries)} queries in {total_time:.3f}s, "
                    f"DB time: {analysis['total_time']:.3f}s"
                )
                
                if analysis['issues']:
                    logger.warning(
                        f"{self.name}: Found {len(analysis['issues'])} query issues"
                    )