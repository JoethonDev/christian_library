import time
import json
import os
import threading
import traceback
import logging
import re
from django.conf import settings
from django.db import connection
from django.utils.deprecation import MiddlewareMixin
from django.utils.timezone import now

# Configuration
LOG_PATH = os.path.join(settings.BASE_DIR, 'logs', 'db_query_metrics.jsonl')
LOG_LOCK = threading.Lock()
N_PLUS_ONE_THRESHOLD = getattr(settings, 'DB_QUERY_N_PLUS_ONE_THRESHOLD', 3)
SLOW_QUERY_THRESHOLD = getattr(settings, 'DB_QUERY_SLOW_THRESHOLD', 0.1)  # 100ms
MAX_STACK_DEPTH = getattr(settings, 'DB_QUERY_MAX_STACK_DEPTH', 10)

logger = logging.getLogger(__name__)


class UnifiedDBQueryMetricsMiddleware(MiddlewareMixin):
    """
    Unified middleware for comprehensive database query monitoring and analysis.
    
    Features:
    - N+1 query detection
    - Duplicate query identification
    - Slow query monitoring
    - Structured JSONL logging for LLM analysis
    - Debug headers in development mode
    """
    
    def process_request(self, request):
        """Reset query log and start timing for this request"""
        if settings.DEBUG:
            connection.queries_log.clear()
        request._db_query_start = time.time()
        return None

    def process_response(self, request, response):
        """Analyze database queries and log comprehensive metrics"""
        try:
            # Calculate request duration
            request_duration = time.time() - getattr(request, '_db_query_start', time.time())
            
            # Get queries (only available in DEBUG mode)
            queries = list(connection.queries) if settings.DEBUG else []
            
            if not queries:
                return response
            
            # Analyze queries
            analysis = self._analyze_queries(queries)
            
            # Prepare log entry
            log_entry = {
                'timestamp': now().isoformat(),
                'request': {
                    'path': request.path,
                    'method': request.method,
                    'user': str(getattr(request, 'user', 'Anonymous')),
                    'remote_addr': request.META.get('REMOTE_ADDR', 'unknown'),
                    'view_func': getattr(request, 'resolver_match', None) and request.resolver_match.view_name,
                },
                'performance': {
                    'total_query_count': len(queries),
                    'total_query_time': analysis['total_time'],
                    'request_duration': request_duration,
                    'slow_queries_count': analysis['slow_queries_count'],
                },
                'issues': {
                    'n_plus_one_detected': analysis['n_plus_one_detected'],
                    'n_plus_one_patterns': analysis['n_plus_one_patterns'],
                    'duplicate_queries_count': len(analysis['duplicate_queries']),
                    'slow_operation': analysis['total_time'] > SLOW_QUERY_THRESHOLD,
                },
                'queries': [
                    {
                        'sql': q['sql'],
                        'time': q['time'],
                        'pattern': self._extract_query_pattern(q['sql']),
                    } for q in queries
                ],
                'stack_trace': traceback.format_stack(limit=MAX_STACK_DEPTH) if settings.DEBUG else [],
            }
            
            # Log structured data to JSONL file
            self._write_log_entry(log_entry)
            
            # Log issues to Django logger
            self._log_issues(request, analysis)
            
            # Add debug headers in development
            if settings.DEBUG:
                self._add_debug_headers(response, analysis, len(queries))
                
        except Exception as e:
            # Don't break the app if logging fails
            logger.error(f"Database metrics logging failed: {str(e)}")
        
        return response
    
    def _analyze_queries(self, queries):
        """Comprehensive analysis of database queries"""
        total_time = sum(float(query.get('time', 0)) for query in queries)
        slow_queries_count = sum(1 for q in queries if float(q.get('time', 0)) > SLOW_QUERY_THRESHOLD)
        
        # N+1 query detection
        query_patterns = {}
        for query in queries:
            sql = query.get('sql', '').strip()
            if sql.lower().startswith('select'):
                pattern = self._extract_query_pattern(sql)
                query_patterns[pattern] = query_patterns.get(pattern, 0) + 1
        
        # Find N+1 patterns
        n_plus_one_patterns = [
            {'pattern': pattern, 'count': count}
            for pattern, count in query_patterns.items()
            if count > N_PLUS_ONE_THRESHOLD
        ]
        
        # Duplicate query detection
        duplicate_queries = self._find_duplicate_queries(queries)
        
        return {
            'total_time': total_time,
            'slow_queries_count': slow_queries_count,
            'n_plus_one_detected': len(n_plus_one_patterns) > 0,
            'n_plus_one_patterns': n_plus_one_patterns,
            'duplicate_queries': duplicate_queries,
        }
    
    def _extract_query_pattern(self, sql):
        """Extract a normalized pattern from SQL query for analysis"""
        sql_lower = sql.lower().strip()
        
        # Replace specific values with placeholders
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
        """Find exact duplicate queries within the request"""
        query_counts = {}
        duplicates = []
        
        for query in queries:
            sql = query.get('sql', '').strip()
            if sql in query_counts:
                query_counts[sql] += 1
                if query_counts[sql] == 2:  # First duplicate
                    duplicates.append({
                        'sql': sql,
                        'count': query_counts[sql]
                    })
            else:
                query_counts[sql] = 1
        
        # Update counts for all duplicates
        for duplicate in duplicates:
            duplicate['count'] = query_counts[duplicate['sql']]
        
        return duplicates
    
    def _write_log_entry(self, log_entry):
        """Write log entry to JSONL file with thread safety"""
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with LOG_LOCK:
                with open(LOG_PATH, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + '\n')
        except Exception as e:
            logger.error(f"Failed to write query metrics log: {str(e)}")
    
    def _log_issues(self, request, analysis):
        """Log detected issues to Django logger"""
        if analysis['n_plus_one_detected']:
            for pattern_info in analysis['n_plus_one_patterns']:
                logger.warning(
                    f"N+1 query detected: {pattern_info['pattern']} "
                    f"(executed {pattern_info['count']} times) "
                    f"for {request.method} {request.path}"
                )
        
        if analysis['total_time'] > SLOW_QUERY_THRESHOLD:
            logger.warning(
                f"Slow database operation: {len(connection.queries)} queries "
                f"in {analysis['total_time']:.3f}s for {request.method} {request.path}"
            )
        
        if analysis['duplicate_queries']:
            logger.warning(
                f"Duplicate queries detected: {len(analysis['duplicate_queries'])} "
                f"duplicates for {request.method} {request.path}"
            )
    
    def _add_debug_headers(self, response, analysis, query_count):
        """Add debug headers in development mode"""
        response['X-DB-Queries-Count'] = str(query_count)
        response['X-DB-Queries-Time'] = f"{analysis['total_time']:.3f}s"
        
        if analysis['n_plus_one_detected']:
            response['X-DB-N-Plus-One'] = 'detected'
        
        if analysis['duplicate_queries']:
            response['X-DB-Duplicates'] = str(len(analysis['duplicate_queries']))
        
        if analysis['total_time'] > SLOW_QUERY_THRESHOLD:
            response['X-DB-Slow-Operation'] = 'true'


# Legacy alias for backward compatibility
DBQueryMetricsMiddleware = UnifiedDBQueryMetricsMiddleware
