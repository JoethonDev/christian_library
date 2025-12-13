"""
Health check, monitoring, and error handling views for Christian Library.
"""

import os
import psutil
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _
from django.template import loader
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, HttpResponseServerError
import logging

from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta

logger = logging.getLogger(__name__)


@never_cache
@require_http_methods(["GET"])
def health_check(request):
    """
    Basic health check endpoint.
    Returns HTTP 200 if the service is healthy.
    """
    return JsonResponse({
        'status': 'healthy',
        'timestamp': os.environ.get('DEPLOYMENT_TIME', 'unknown'),
        'version': getattr(settings, 'VERSION', '1.0.0')
    })


@never_cache
@require_http_methods(["GET"])
def detailed_health_check(request):
    """
    Detailed health check with dependency status.
    Requires monitoring token for access.
    """
    # Check authorization
    token = request.GET.get('token') or request.META.get('HTTP_X_MONITORING_TOKEN')
    expected_token = getattr(settings, 'MONITORING_TOKEN', '')
    
    if not expected_token or token != expected_token:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    health_data = {
        'status': 'healthy',
        'timestamp': os.environ.get('DEPLOYMENT_TIME', 'unknown'),
        'version': getattr(settings, 'VERSION', '1.0.0'),
        'checks': {}
    }

    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_data['checks']['database'] = {
            'status': 'healthy',
            'response_time_ms': 0  # Could measure actual response time
        }
    except Exception as e:
        health_data['checks']['database'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
        health_data['status'] = 'unhealthy'

    # Redis check (if configured)
    if hasattr(settings, 'CACHES') and 'redis' in str(settings.CACHES.get('default', {})):
        try:
            from django.core.cache import cache
            cache.set('health_check', 'ok', 60)
            result = cache.get('health_check')
            health_data['checks']['redis'] = {
                'status': 'healthy' if result == 'ok' else 'unhealthy'
            }
        except Exception as e:
            health_data['checks']['redis'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_data['status'] = 'unhealthy'

    # Disk space check
    try:
        disk_usage = psutil.disk_usage('/')
        disk_usage_percent = (disk_usage.used / disk_usage.total) * 100
        
        health_data['checks']['disk_space'] = {
            'status': 'healthy' if disk_usage_percent < 90 else 'warning',
            'usage_percent': round(disk_usage_percent, 2),
            'free_gb': round(disk_usage.free / (1024**3), 2)
        }
        
        if disk_usage_percent > 95:
            health_data['status'] = 'unhealthy'
    except Exception as e:
        health_data['checks']['disk_space'] = {
            'status': 'error',
            'error': str(e)
        }

    # Memory check
    try:
        memory = psutil.virtual_memory()
        memory_usage_percent = memory.percent
        
        health_data['checks']['memory'] = {
            'status': 'healthy' if memory_usage_percent < 90 else 'warning',
            'usage_percent': memory_usage_percent,
            'available_gb': round(memory.available / (1024**3), 2)
        }
        
        if memory_usage_percent > 95:
            health_data['status'] = 'unhealthy'
    except Exception as e:
        health_data['checks']['memory'] = {
            'status': 'error',
            'error': str(e)
        }

    # Application-specific checks
    try:
        # Check content counts
        course_count = Course.objects.count()
        content_count = ContentItem.objects.count()
        video_count = VideoMeta.objects.count()
        audio_count = AudioMeta.objects.count()
        pdf_count = PdfMeta.objects.count()
        
        health_data['checks']['application'] = {
            'status': 'healthy',
            'metrics': {
                'courses': course_count,
                'content_items': content_count,
                'videos': video_count,
                'audios': audio_count,
                'pdfs': pdf_count
            }
        }
    except Exception as e:
        health_data['checks']['application'] = {
            'status': 'error',
            'error': str(e)
        }
        health_data['status'] = 'unhealthy'

    # Set HTTP status based on overall health
    status_code = 200 if health_data['status'] == 'healthy' else 503
    
    return JsonResponse(health_data, status=status_code)


@never_cache
@require_http_methods(["GET"])
def system_metrics(request):
    """
    System metrics endpoint for monitoring.
    Requires monitoring token for access.
    """
    # Check authorization
    token = request.GET.get('token') or request.META.get('HTTP_X_MONITORING_TOKEN')
    expected_token = getattr(settings, 'MONITORING_TOKEN', '')
    
    if not expected_token or token != expected_token:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Memory metrics
        memory = psutil.virtual_memory()
        
        # Disk metrics
        disk = psutil.disk_usage('/')
        
        # Network metrics (if available)
        network_io = psutil.net_io_counters()
        
        # Process metrics
        process = psutil.Process()
        process_memory = process.memory_info()
        
        metrics = {
            'timestamp': os.environ.get('DEPLOYMENT_TIME', 'unknown'),
            'system': {
                'cpu': {
                    'usage_percent': cpu_percent,
                    'core_count': cpu_count
                },
                'memory': {
                    'total_gb': round(memory.total / (1024**3), 2),
                    'available_gb': round(memory.available / (1024**3), 2),
                    'used_gb': round(memory.used / (1024**3), 2),
                    'usage_percent': memory.percent
                },
                'disk': {
                    'total_gb': round(disk.total / (1024**3), 2),
                    'free_gb': round(disk.free / (1024**3), 2),
                    'used_gb': round(disk.used / (1024**3), 2),
                    'usage_percent': round((disk.used / disk.total) * 100, 2)
                },
                'network': {
                    'bytes_sent': network_io.bytes_sent,
                    'bytes_recv': network_io.bytes_recv,
                    'packets_sent': network_io.packets_sent,
                    'packets_recv': network_io.packets_recv
                }
            },
            'process': {
                'memory_mb': round(process_memory.rss / (1024**2), 2),
                'cpu_percent': process.cpu_percent(),
                'threads': process.num_threads()
            }
        }
        
        return JsonResponse(metrics)
        
    except Exception as e:
        return JsonResponse({
            'error': 'Failed to collect metrics',
            'details': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def readiness_probe(request):
    """
    Kubernetes readiness probe endpoint.
    Checks if the application is ready to receive traffic.
    """
    try:
        # Quick database check
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return JsonResponse({'status': 'ready'})
        
    except Exception as e:
        return JsonResponse({
            'status': 'not_ready',
            'error': str(e)
        }, status=503)


@csrf_exempt
@require_http_methods(["POST"])
def liveness_probe(request):
    """
    Kubernetes liveness probe endpoint.
    Checks if the application is alive and responsive.
    """
    return JsonResponse({'status': 'alive'})


# Custom Error Handlers

def custom_bad_request(request, exception):
    """Handle 400 Bad Request errors"""
    logger.warning(f"400 Bad Request: {request.path} - {str(exception)}")
    
    context = {
        'error_code': 400,
        'error_title': _('Bad Request'),
        'error_message': _('The request could not be understood by the server.'),
        'show_home_link': True,
    }
    
    if request.headers.get('Accept', '').startswith('application/json'):
        return JsonResponse({
            'error': 'bad_request',
            'message': str(context['error_message']),
            'code': 400
        }, status=400)
    
    template = loader.get_template('errors/400.html')
    return HttpResponseBadRequest(template.render(context, request))


def custom_permission_denied(request, exception):
    """Handle 403 Permission Denied errors"""
    logger.warning(f"403 Permission Denied: {request.path} - User: {getattr(request.user, 'username', 'Anonymous')}")
    
    context = {
        'error_code': 403,
        'error_title': _('Permission Denied'),
        'error_message': _('You do not have permission to access this resource.'),
        'show_home_link': True,
        'show_login_link': not request.user.is_authenticated,
    }
    
    if request.headers.get('Accept', '').startswith('application/json'):
        return JsonResponse({
            'error': 'permission_denied',
            'message': str(context['error_message']),
            'code': 403
        }, status=403)
    
    template = loader.get_template('errors/403.html')
    return HttpResponseForbidden(template.render(context, request))


def custom_page_not_found(request, exception):
    """Handle 404 Page Not Found errors"""
    logger.info(f"404 Page Not Found: {request.path}")
    
    context = {
        'error_code': 404,
        'error_title': _('Page Not Found'),
        'error_message': _('The page you are looking for could not be found.'),
        'show_home_link': True,
        'show_search': True,
        'requested_path': request.path,
    }
    
    if request.headers.get('Accept', '').startswith('application/json'):
        return JsonResponse({
            'error': 'not_found',
            'message': str(context['error_message']),
            'code': 404
        }, status=404)
    
    template = loader.get_template('errors/404.html')
    return HttpResponseNotFound(template.render(context, request))


def custom_server_error(request):
    """Handle 500 Internal Server errors"""
    logger.error(f"500 Internal Server Error: {request.path}")
    
    context = {
        'error_code': 500,
        'error_title': _('Internal Server Error'),
        'error_message': _('An internal server error occurred. Please try again later.'),
        'show_home_link': True,
        'show_contact': True,
    }
    
    if request.headers.get('Accept', '').startswith('application/json'):
        return JsonResponse({
            'error': 'internal_error', 
            'message': str(context['error_message']),
            'code': 500
        }, status=500)
    
    try:
        template = loader.get_template('errors/500.html')
        return HttpResponseServerError(template.render(context, request))
    except Exception:
        # Fallback if template loading fails
        return HttpResponseServerError(
            f"<h1>{context['error_title']}</h1><p>{context['error_message']}</p>"
        )