from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Avg, Q
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta
import os
import psutil
# from apps.courses.models import Course  # Course functionality removed
from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta


@staff_member_required
def admin_dashboard(request):
    """Custom admin dashboard with comprehensive stats"""
    
    # Basic content stats
    total_courses = Course.objects.count()
    total_videos = ContentItem.objects.filter(content_type='video').count()
    total_audios = ContentItem.objects.filter(content_type='audio').count()
    total_pdfs = ContentItem.objects.filter(content_type='pdf').count()
    
    # Recent content
    recent_uploads = ContentItem.objects.select_related('videometa', 'audiometa', 'pdfmeta').order_by('-created_at')[:10]
    
    # Processing stats
    video_processing_stats = VideoMeta.objects.values('processing_status').annotate(count=Count('processing_status'))
    audio_processing_stats = AudioMeta.objects.values('processing_status').annotate(count=Count('processing_status'))
    pdf_processing_stats = PdfMeta.objects.values('processing_status').annotate(count=Count('processing_status'))
    
    # Course stats
    course_stats = Course.objects.annotate(
        content_count=Count('modules__contentitem'),
        video_count=Count('modules__contentitem', filter=Q(modules__contentitem__content_type='video')),
        audio_count=Count('modules__contentitem', filter=Q(modules__contentitem__content_type='audio')),
        pdf_count=Count('modules__contentitem', filter=Q(modules__contentitem__content_type='pdf'))
    ).order_by('-content_count')[:5]
    
    # System stats
    disk_usage = get_disk_usage_stats()
    
    # Weekly upload stats
    last_week = timezone.now() - timedelta(days=7)
    weekly_uploads = ContentItem.objects.filter(created_at__gte=last_week).extra({
        'day': 'date(created_at)'
    }).values('day', 'content_type').annotate(count=Count('id')).order_by('day')
    
    context = {
        'total_courses': total_courses,
        'total_videos': total_videos,
        'total_audios': total_audios,
        'total_pdfs': total_pdfs,
        'total_content': total_videos + total_audios + total_pdfs,
        'recent_uploads': recent_uploads,
        'video_processing_stats': video_processing_stats,
        'audio_processing_stats': audio_processing_stats,
        'pdf_processing_stats': pdf_processing_stats,
        'course_stats': course_stats,
        'disk_usage': disk_usage,
        'weekly_uploads': weekly_uploads,
        'processing_queue_length': get_celery_queue_length(),
    }
    
    return render(request, 'admin/custom_dashboard.html', context)


@staff_member_required
def content_management(request):
    """Content management interface"""
    content_type = request.GET.get('type', 'all')
    status_filter = request.GET.get('status', 'all')
    course_filter = request.GET.get('course', 'all')
    
    # Base queryset
    queryset = ContentItem.objects.select_related('module__course').prefetch_related('videometa', 'audiometa', 'pdfmeta')
    
    # Apply filters
    if content_type != 'all':
        queryset = queryset.filter(content_type=content_type)
    
    if course_filter != 'all':
        queryset = queryset.filter(module__course_id=course_filter)
    
    if status_filter != 'all':
        if content_type == 'video':
            queryset = queryset.filter(videometa__processing_status=status_filter)
        elif content_type == 'audio':
            queryset = queryset.filter(audiometa__processing_status=status_filter)
        elif content_type == 'pdf':
            queryset = queryset.filter(pdfmeta__processing_status=status_filter)
    
    content_items = queryset.order_by('-created_at')
    courses = Course.objects.all()
    
    context = {
        'content_items': content_items,
        'courses': courses,
        'current_type': content_type,
        'current_status': status_filter,
        'current_course': course_filter,
    }
    
    return render(request, 'admin/content_management.html', context)


@staff_member_required
def bulk_operations(request):
    """Bulk operations interface"""
    if request.method == 'POST':
        action = request.POST.get('action')
        selected_items = request.POST.getlist('selected_items')
        
        if not selected_items:
            return JsonResponse({'success': False, 'error': 'No items selected'})
        
        if action == 'delete':
            ContentItem.objects.filter(id__in=selected_items).delete()
            return JsonResponse({'success': True, 'message': f'Deleted {len(selected_items)} items'})
        
        elif action == 'activate':
            ContentItem.objects.filter(id__in=selected_items).update(is_active=True)
            return JsonResponse({'success': True, 'message': f'Activated {len(selected_items)} items'})
        
        elif action == 'deactivate':
            ContentItem.objects.filter(id__in=selected_items).update(is_active=False)
            return JsonResponse({'success': True, 'message': f'Deactivated {len(selected_items)} items'})
        
        elif action == 'reprocess':
            # Queue reprocessing tasks
            for item_id in selected_items:
                try:
                    content_item = ContentItem.objects.get(id=item_id)
                    queue_reprocessing_task(content_item)
                except ContentItem.DoesNotExist:
                    continue
            return JsonResponse({'success': True, 'message': f'Queued {len(selected_items)} items for reprocessing'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@staff_member_required
def system_monitor(request):
    """System monitoring interface"""
    
    # Processing queue stats
    queue_stats = {
        'video_queue': get_queue_length('video_processing'),
        'audio_queue': get_queue_length('audio_processing'),
        'pdf_queue': get_queue_length('pdf_processing'),
        'total_active_tasks': get_active_tasks_count(),
    }
    
    # Disk usage by content type
    media_stats = get_detailed_media_stats()
    
    # Recent errors
    recent_errors = get_recent_processing_errors()
    
    # System health
    system_health = {
        'cpu_usage': psutil.cpu_percent(interval=1),
        'memory_usage': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('/').percent,
        'celery_workers': get_celery_workers_status(),
    }
    
    context = {
        'queue_stats': queue_stats,
        'media_stats': media_stats,
        'recent_errors': recent_errors,
        'system_health': system_health,
    }
    
    return render(request, 'admin/system_monitor.html', context)


def get_disk_usage_stats():
    """Get disk usage statistics"""
    try:
        # Get media directory path
        media_root = '/app/media'  # Docker path
        if not os.path.exists(media_root):
            media_root = 'media'  # Local development path
        
        if os.path.exists(media_root):
            # Calculate directory sizes
            total_size = 0
            video_size = 0
            audio_size = 0
            pdf_size = 0
            
            for root, dirs, files in os.walk(media_root):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    
                    if 'video' in root.lower():
                        video_size += file_size
                    elif 'audio' in root.lower():
                        audio_size += file_size
                    elif 'pdf' in root.lower():
                        pdf_size += file_size
            
            return {
                'total_size': total_size,
                'video_size': video_size,
                'audio_size': audio_size,
                'pdf_size': pdf_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'video_size_mb': round(video_size / (1024 * 1024), 2),
                'audio_size_mb': round(audio_size / (1024 * 1024), 2),
                'pdf_size_mb': round(pdf_size / (1024 * 1024), 2),
            }
    except Exception as e:
        return {'error': str(e)}
    
    return {'total_size': 0, 'video_size': 0, 'audio_size': 0, 'pdf_size': 0}


def get_celery_queue_length():
    """Get Celery queue length"""
    try:
        # This would require celery inspection - simplified for now
        return 0
    except:
        return 0


def get_queue_length(queue_name):
    """Get specific queue length"""
    try:
        # Implementation would depend on Celery setup
        return 0
    except:
        return 0


def get_active_tasks_count():
    """Get active Celery tasks count"""
    try:
        # Implementation would depend on Celery setup
        return 0
    except:
        return 0


def get_detailed_media_stats():
    """Get detailed media statistics"""
    return {
        'original_videos': VideoMeta.objects.exclude(original_file='').count(),
        'processed_videos': VideoMeta.objects.exclude(hls_720p_path='').count(),
        'compressed_audios': AudioMeta.objects.exclude(compressed_file='').count(),
        'total_pdfs': PdfMeta.objects.count(),
    }


def get_recent_processing_errors():
    """Get recent processing errors"""
    # This would typically come from logs or error tracking
    return []


def get_celery_workers_status():
    """Get Celery workers status"""
    try:
        # Implementation would depend on Celery setup
        return {'active': 1, 'total': 1}
    except:
        return {'active': 0, 'total': 0}


def queue_reprocessing_task(content_item):
    """Queue item for reprocessing"""
    # Implementation would queue appropriate Celery task based on content type
    pass