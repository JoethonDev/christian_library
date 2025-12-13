"""
Performance monitoring middleware for tracking request metrics.
"""

import time
import logging
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.conf import settings
from django.db import connection
import psutil
import os

logger = logging.getLogger(__name__)


class PerformanceMonitoringMiddleware(MiddlewareMixin):
    """Monitor request performance and log slow requests"""
    
    def process_request(self, request):
        """Start timing the request"""
        request._performance_start_time = time.time()
        request._performance_queries_before = len(connection.queries)
        return None
    
    def process_response(self, request, response):
        """Log performance metrics"""
        if not hasattr(request, '_performance_start_time'):
            return response
            
        # Calculate metrics
        total_time = time.time() - request._performance_start_time
        queries_count = len(connection.queries) - request._performance_queries_before
        
        # Get memory usage
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        # Log slow requests (over 2 seconds)
        if total_time > 2.0:
            logger.warning(
                f"Slow request: {request.method} {request.path} - "
                f"{total_time:.3f}s, {queries_count} queries, {memory_mb:.1f}MB"
            )
        
        # Log all requests in debug mode
        if settings.DEBUG:
            logger.debug(
                f"Request: {request.method} {request.path} - "
                f"{total_time:.3f}s, {queries_count} queries, {memory_mb:.1f}MB"
            )
        
        # Store metrics for monitoring
        if hasattr(response, 'status_code'):
            cache_key = f"perf_metrics_{int(time.time() // 60)}"  # Per minute bucket
            metrics = cache.get(cache_key, {
                'requests': 0,
                'total_time': 0,
                'total_queries': 0,
                'slow_requests': 0,
                'errors': 0
            })
            
            metrics['requests'] += 1
            metrics['total_time'] += total_time
            metrics['total_queries'] += queries_count
            
            if total_time > 2.0:
                metrics['slow_requests'] += 1
            
            if response.status_code >= 400:
                metrics['errors'] += 1
            
            cache.set(cache_key, metrics, 300)  # Keep for 5 minutes
        
        # Add performance headers in debug mode
        if settings.DEBUG:
            response['X-Response-Time'] = f"{total_time:.3f}s"
            response['X-DB-Queries'] = str(queries_count)
            response['X-Memory-Usage'] = f"{memory_mb:.1f}MB"
        
        return response