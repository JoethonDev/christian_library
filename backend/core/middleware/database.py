"""
Database optimization middleware for query monitoring and optimization.
"""

import logging
from django.utils.deprecation import MiddlewareMixin
from django.db import connection
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class DatabaseOptimizationMiddleware(MiddlewareMixin):
    """Monitor and optimize database queries"""
    
    def process_request(self, request):
        """Reset query count"""
        if settings.DEBUG:
            connection.queries_log.clear()
        return None
    
    def process_response(self, request, response):
        """Analyze database queries"""
        if not settings.DEBUG:
            return response
        
        queries = connection.queries
        total_queries = len(queries)
        
        if total_queries == 0:
            return response
        
        # Calculate total query time
        total_time = sum(float(query.get('time', 0)) for query in queries)
        
        # Detect N+1 queries
        query_patterns = {}
        for query in queries:
            sql = query.get('sql', '').strip()
            # Extract table and operation pattern
            if sql.lower().startswith('select'):
                # Simple pattern matching for similar queries
                pattern = self._extract_query_pattern(sql)
                query_patterns[pattern] = query_patterns.get(pattern, 0) + 1
        
        # Log potential N+1 queries (same pattern repeated > 3 times)
        n_plus_one_detected = False
        for pattern, count in query_patterns.items():
            if count > 3:
                logger.warning(f"Potential N+1 query detected: {pattern} (executed {count} times)")
                n_plus_one_detected = True
        
        # Log slow database operations
        if total_time > 0.1:  # 100ms threshold
            logger.warning(
                f"Slow database operation: {total_queries} queries in {total_time:.3f}s "
                f"for {request.method} {request.path}"
            )
        
        # Log duplicate queries
        duplicate_queries = self._find_duplicate_queries(queries)
        if duplicate_queries:
            logger.warning(f"Duplicate queries detected: {len(duplicate_queries)} duplicates")
        
        # Add database performance headers
        if settings.DEBUG:
            response['X-DB-Queries-Count'] = str(total_queries)
            response['X-DB-Queries-Time'] = f"{total_time:.3f}s"
            if n_plus_one_detected:
                response['X-DB-N-Plus-One'] = 'detected'
        
        return response
    
    def _extract_query_pattern(self, sql):
        """Extract a pattern from SQL query for N+1 detection"""
        # Simple pattern extraction - normalize SQL
        sql_lower = sql.lower().strip()
        
        # Remove specific values and keep structure
        import re
        
        # Replace numbers, strings, and UUIDs with placeholders
        pattern = re.sub(r"'[^']*'", "'?'", sql_lower)
        pattern = re.sub(r'"[^"]*"', '"?"', pattern)
        pattern = re.sub(r'\b\d+\b', '?', pattern)
        pattern = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '?', pattern)
        
        # Extract table name and basic operation
        if 'select' in pattern and 'from' in pattern:
            try:
                from_idx = pattern.find('from ')
                if from_idx != -1:
                    table_part = pattern[from_idx + 5:].split()[0]
                    return f"SELECT from {table_part}"
            except (IndexError, AttributeError):
                pass
        
        return pattern[:100]  # Truncate long patterns
    
    def _find_duplicate_queries(self, queries):
        """Find exact duplicate queries"""
        query_counts = {}
        duplicates = []
        
        for query in queries:
            sql = query.get('sql', '').strip()
            if sql in query_counts:
                query_counts[sql] += 1
                if query_counts[sql] == 2:  # First duplicate
                    duplicates.append(sql)
            else:
                query_counts[sql] = 1
        
        return duplicates