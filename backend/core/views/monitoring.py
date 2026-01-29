"""
Monitoring views for application health and performance monitoring.
"""

from django.http import JsonResponse
from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.db import connection
from datetime import datetime
import json
import psutil

from core.utils.monitoring import StructuredLogger
from core.utils.log_analysis import log_analyzer, alert_manager
from core.utils.database_optimization import QueryAnalyzer


logger = StructuredLogger('monitoring_views')


@method_decorator([staff_member_required, never_cache], name='dispatch')
class MonitoringDashboardView(TemplateView):
    """Main monitoring dashboard"""
    template_name = 'admin/monitoring/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        try:
            # Get system metrics
            context['system_metrics'] = self._get_system_metrics()
            
            # Get application health
            context['health_report'] = log_analyzer.generate_health_report()
            
            # Get recent alerts
            context['recent_alerts'] = cache.get('recent_alerts', [])[:10]
            
            # Get performance metrics
            context['performance_metrics'] = self._get_performance_summary()
            
            # Get error summary
            context['error_summary'] = self._get_error_summary()
            
        except Exception as e:
            logger.log_error(e, {'view': 'MonitoringDashboardView'})
            context['error'] = 'Failed to load monitoring data'
        
        return context
    
    def _get_system_metrics(self):
        """Get current system metrics"""
        try:
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent,
                'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else [0, 0, 0],
                'process_count': len(psutil.pids()),
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.log_error(e, {'method': '_get_system_metrics'})
            return {}
    
    def _get_performance_summary(self):
        """Get performance metrics summary"""
        try:
            current_minute = int(datetime.utcnow().timestamp() // 60)
            summary = {
                'operations_per_minute': 0,
                'avg_response_time': 0,
                'slow_operations': 0
            }
            
            # Check last 5 minutes
            total_operations = 0
            total_time = 0
            slow_count = 0
            
            for minute in range(5):
                minute_key = current_minute - minute
                cache_key = f"perf_metric_view_render_{minute_key}"
                metric_data = cache.get(cache_key)
                
                if metric_data:
                    total_operations += metric_data.get('count', 0)
                    total_time += metric_data.get('total_time', 0)
                    
                    if metric_data.get('avg_time', 0) > 2.0:
                        slow_count += 1
            
            if total_operations > 0:
                summary['operations_per_minute'] = total_operations / 5
                summary['avg_response_time'] = total_time / total_operations
            
            summary['slow_operations'] = slow_count
            
            return summary
            
        except Exception as e:
            logger.log_error(e, {'method': '_get_performance_summary'})
            return {}
    
    def _get_error_summary(self):
        """Get error summary"""
        try:
            current_hour = int(datetime.utcnow().timestamp() // 3600)
            summary = {
                'errors_this_hour': 0,
                'error_types': [],
                'trending_up': False
            }
            
            # Count current hour errors
            for error_type in ['ValueError', 'TypeError', 'KeyError', 'AttributeError']:
                cache_key = f"error_count_{error_type}_{current_hour}"
                count = cache.get(cache_key, 0)
                summary['errors_this_hour'] += count
                
                if count > 0:
                    summary['error_types'].append({
                        'type': error_type,
                        'count': count
                    })
            
            # Check if trending up (compare with previous hour)
            prev_hour_count = 0
            for error_type in ['ValueError', 'TypeError', 'KeyError', 'AttributeError']:
                cache_key = f"error_count_{error_type}_{current_hour - 1}"
                prev_hour_count += cache.get(cache_key, 0)
            
            summary['trending_up'] = summary['errors_this_hour'] > prev_hour_count * 1.2
            
            return summary
            
        except Exception as e:
            logger.log_error(e, {'method': '_get_error_summary'})
            return {}


@staff_member_required
@never_cache
def system_metrics_api(request):
    """API endpoint for real-time system metrics"""
    try:
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'cpu': {
                'percent': psutil.cpu_percent(interval=0.1),
                'count': psutil.cpu_count(),
                'load_avg': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else [0, 0, 0]
            },
            'memory': {
                'percent': psutil.virtual_memory().percent,
                'available': psutil.virtual_memory().available,
                'total': psutil.virtual_memory().total
            },
            'disk': {
                'usage_percent': psutil.disk_usage('/').percent,
                'free': psutil.disk_usage('/').free,
                'total': psutil.disk_usage('/').total
            },
            'network': {
                'bytes_sent': psutil.net_io_counters().bytes_sent,
                'bytes_recv': psutil.net_io_counters().bytes_recv,
                'packets_sent': psutil.net_io_counters().packets_sent,
                'packets_recv': psutil.net_io_counters().packets_recv
            }
        }
        
        return JsonResponse(metrics)
        
    except Exception as e:
        logger.log_error(e, {'api': 'system_metrics'})
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@never_cache
def performance_metrics_api(request):
    """API endpoint for performance metrics"""
    try:
        hours = int(request.GET.get('hours', 1))
        metrics = log_analyzer.analyze_performance_metrics(hours)
        
        # Add current database connection info
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                active_connections = cursor.fetchone()[0]
                
                cursor.execute("SELECT setting FROM pg_settings WHERE name = 'max_connections'")
                max_connections = cursor.fetchone()[0]
                
                metrics['database'] = {
                    'active_connections': active_connections,
                    'max_connections': int(max_connections),
                    'connection_usage_percent': (active_connections / int(max_connections)) * 100
                }
        except Exception:
            metrics['database'] = {'error': 'Unable to fetch database metrics'}
        
        return JsonResponse(metrics)
        
    except Exception as e:
        logger.log_error(e, {'api': 'performance_metrics'})
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@never_cache
def error_analysis_api(request):
    """API endpoint for error analysis"""
    try:
        hours = int(request.GET.get('hours', 24))
        analysis = log_analyzer.analyze_error_patterns(hours)
        
        return JsonResponse(analysis)
        
    except Exception as e:
        logger.log_error(e, {'api': 'error_analysis'})
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@never_cache
def alerts_api(request):
    """API endpoint for alerts"""
    try:
        if request.method == 'GET':
            # Get current alerts
            alerts = alert_manager.check_alerts()
            recent_alerts = cache.get('recent_alerts', [])
            
            return JsonResponse({
                'current_alerts': alerts,
                'recent_alerts': recent_alerts
            })
        
        elif request.method == 'POST':
            # Process a new alert
            alert_data = json.loads(request.body)
            success = alert_manager.process_alert(alert_data)
            
            return JsonResponse({
                'success': success,
                'message': 'Alert processed successfully' if success else 'Failed to process alert'
            })
        
    except Exception as e:
        logger.log_error(e, {'api': 'alerts'})
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@never_cache
def query_analysis_api(request):
    """API endpoint for database query analysis"""
    try:
        # Get recent slow queries from cache
        slow_queries = cache.get('slow_queries', [])
        
        # Analyze current query performance
        analyzer = QueryAnalyzer()
        analysis = {
            'slow_queries': slow_queries[:20],  # Last 20 slow queries
            'query_stats': analyzer.get_query_stats(),
            'recommendations': []
        }
        
        # Add recommendations based on analysis
        if len(slow_queries) > 10:
            analysis['recommendations'].append({
                'type': 'performance',
                'message': 'High number of slow queries detected. Consider query optimization.',
                'priority': 'high'
            })
        
        # Check for N+1 patterns in recent queries
        n_plus_one_count = sum(1 for q in slow_queries if 'N+1' in q.get('analysis', ''))
        if n_plus_one_count > 5:
            analysis['recommendations'].append({
                'type': 'n_plus_one',
                'message': f'{n_plus_one_count} potential N+1 queries detected. Use select_related/prefetch_related.',
                'priority': 'medium'
            })
        
        return JsonResponse(analysis)
        
    except Exception as e:
        logger.log_error(e, {'api': 'query_analysis'})
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@never_cache
def health_check_api(request):
    """API endpoint for application health check"""
    try:
        health_report = log_analyzer.generate_health_report()
        
        # Add real-time checks
        health_checks = {
            'database': _check_database_health(),
            'cache': _check_cache_health(),
            'disk_space': _check_disk_space(),
            'memory': _check_memory_usage()
        }
        
        # Overall health status
        all_checks_pass = all(check['status'] == 'healthy' for check in health_checks.values())
        overall_status = 'healthy' if all_checks_pass else 'unhealthy'
        
        return JsonResponse({
            'status': overall_status,
            'health_score': health_report.get('overall_health_score', 0),
            'checks': health_checks,
            'report': health_report,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.log_error(e, {'api': 'health_check'})
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }, status=500)


def _check_database_health():
    """Check database connectivity and performance"""
    try:
        start_time = datetime.utcnow()
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
        
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        return {
            'status': 'healthy' if response_time < 1.0 else 'slow',
            'response_time': response_time,
            'message': f'Database responding in {response_time:.3f}s'
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Database connection failed'
        }


def _check_cache_health():
    """Check cache connectivity"""
    try:
        test_key = f'health_check_{int(datetime.utcnow().timestamp())}'
        cache.set(test_key, 'test', 60)
        result = cache.get(test_key)
        cache.delete(test_key)
        
        return {
            'status': 'healthy' if result == 'test' else 'error',
            'message': 'Cache is functioning properly' if result == 'test' else 'Cache test failed'
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Cache connection failed'
        }


def _check_disk_space():
    """Check available disk space"""
    try:
        disk_usage = psutil.disk_usage('/')
        usage_percent = (disk_usage.used / disk_usage.total) * 100
        
        if usage_percent > 90:
            status = 'critical'
            message = f'Disk usage critical: {usage_percent:.1f}%'
        elif usage_percent > 80:
            status = 'warning'
            message = f'Disk usage high: {usage_percent:.1f}%'
        else:
            status = 'healthy'
            message = f'Disk usage normal: {usage_percent:.1f}%'
        
        return {
            'status': status,
            'usage_percent': usage_percent,
            'free_gb': disk_usage.free / (1024**3),
            'message': message
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Unable to check disk space'
        }


def _check_memory_usage():
    """Check memory usage"""
    try:
        memory = psutil.virtual_memory()
        usage_percent = memory.percent
        
        if usage_percent > 95:
            status = 'critical'
            message = f'Memory usage critical: {usage_percent:.1f}%'
        elif usage_percent > 85:
            status = 'warning'
            message = f'Memory usage high: {usage_percent:.1f}%'
        else:
            status = 'healthy'
            message = f'Memory usage normal: {usage_percent:.1f}%'
        
        return {
            'status': status,
            'usage_percent': usage_percent,
            'available_gb': memory.available / (1024**3),
            'message': message
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Unable to check memory usage'
        }