"""
Admin Views for Content Management
Handles all administrative operations with full RTL/LTR and localization support
"""
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
from apps.media_manager.services.content_service import ContentService
from apps.media_manager.services.upload_service import MediaUploadService


# Initialize services
content_service = ContentService()


@login_required
def admin_dashboard(request):
    """Main admin dashboard with statistics and overview"""
    current_language = get_language()
    
    # Get content statistics
    stats = content_service.get_content_statistics()
    
    # Get recent content
    recent_content = ContentItem.objects.prefetch_related('tags').order_by('-created_at')[:10]
    
    # Get processing status for videos
    processing_videos = VideoMeta.objects.filter(
        processing_status__in=['pending', 'processing', 'queued']
    ).select_related('content_item').count()
    
    context = {
        'stats': stats,
        'recent_content': recent_content,
        'processing_videos': processing_videos,
        'current_language': current_language,
    }
    
    return render(request, 'admin/dashboard.html', context)


@login_required
def content_list(request):
    """List all content with filtering and pagination"""
    current_language = get_language()
    
    # Get filters from request
    content_type = request.GET.get('type', '')
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    
    # Get content list
    content_items = content_service.get_content_list(
        content_type=content_type,
        search_query=search_query,
        language=current_language
    )
    
    # Manual pagination
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    
    paginator = Paginator(content_items, 20)  # 20 items per page
    try:
        content_page = paginator.page(page)
    except PageNotAnInteger:
        content_page = paginator.page(1)
    except EmptyPage:
        content_page = paginator.page(paginator.num_pages)
    
    content_data = {
        'content_items': content_page,
        'total_count': paginator.count,
        'current_page': content_page.number,
        'total_pages': paginator.num_pages,
        'has_previous': content_page.has_previous(),
        'has_next': content_page.has_next(),
    }
    
    context = {
        'content_data': content_data,
        'content_type_filter': content_type,
        'search_query': search_query,
        'current_language': current_language,
        'content_types': ContentItem.CONTENT_TYPES,
    }
    
    # Return JSON for HTMX requests
    if request.headers.get('HX-Request'):
        return render(request, 'admin/partials/content_list.html', context)
    
    return render(request, 'admin/content_list.html', context)


@login_required
def upload_content(request):
    """Upload content form and handler"""
    current_language = get_language()
    content_type = request.GET.get('type', 'video')
    
    if request.method == 'POST':
        return handle_content_upload(request)
    
    # Get available tags
    available_tags = Tag.objects.filter(is_active=True).order_by('name_ar')
    
    context = {
        'content_type': content_type,
        'available_tags': available_tags,
        'current_language': current_language,
    }
    
    return render(request, 'admin/upload_content.html', context)


@require_POST
@login_required
def handle_content_upload(request):
    """Handle file upload with validation and processing"""
    try:
        # Extract form data
        title_ar = request.POST.get('title_ar', '').strip()
        title_en = request.POST.get('title_en', '').strip()
        description_ar = request.POST.get('description_ar', '').strip()
        description_en = request.POST.get('description_en', '').strip()
        content_type = request.POST.get('content_type', 'video')
        tags_str = request.POST.get('tags', '').strip()
        
        # Validate required fields
        if not title_ar:
            messages.error(request, _('Arabic title is required'))
            return redirect('frontend_api:upload_content')
        
        if 'file' not in request.FILES:
            messages.error(request, _('Please select a file to upload'))
            return redirect('frontend_api:upload_content')
        
        file = request.FILES['file']
        
        # Validate file type
        valid_extensions = {
            'video': ['.mp4', '.avi', '.mov', '.mkv', '.wmv'],
            'audio': ['.mp3', '.wav', '.flac', '.aac', '.ogg'],
            'pdf': ['.pdf']
        }
        
        file_ext = file.name.lower().split('.')[-1]
        if f'.{file_ext}' not in valid_extensions.get(content_type, []):
            messages.error(request, _('Invalid file type for selected content type'))
            return redirect('frontend_api:upload_content')
        
        # Process tags - convert tag names to tag IDs
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
        tag_ids = []
        if tags:
            for tag_name in tags:
                tag_name = tag_name.strip()
                if tag_name:
                    tag, created = Tag.objects.get_or_create(
                        name_ar=tag_name,
                        defaults={'name_en': tag_name, 'color': '#B8860B'}
                    )
                    tag_ids.append(str(tag.id))
        # Upload based on content type
        if content_type == 'video':
            success, message, content_item = MediaUploadService.upload_video(
                file, title_ar, title_en, description_ar, description_en, tag_ids
            )
        elif content_type == 'audio':
            success, message, content_item = MediaUploadService.upload_audio(
                file, title_ar, description_ar, title_en, description_en, tag_ids
            )
        elif content_type == 'pdf':
            success, message, content_item = MediaUploadService.upload_pdf(
                file, title_ar, description_ar, title_en, description_en, tag_ids
            )
        else:
            success, message, content_item = False, _('Invalid content type'), None
        
        if success:
            messages.success(request, message)
            return redirect('frontend_api:admin_content_detail', content_id=content_item.id)
        else:
            messages.error(request, message)
            
    except Exception as e:
        messages.error(request, f"{_('Upload failed')}: {str(e)}")
    
    return redirect('frontend_api:upload_content')


@login_required
def content_detail(request, content_id):
    """View and edit content details"""
    current_language = get_language()
    content_item = get_object_or_404(ContentItem, id=content_id)
    
    if request.method == 'POST':
        return handle_content_update(request, content_item)
    
    # Get available tags
    available_tags = Tag.objects.filter(is_active=True).order_by('name_ar')
    
    # Get content-specific metadata
    meta_data = None
    if content_item.content_type == 'video':
        meta_data = getattr(content_item, 'videometa', None)
    elif content_item.content_type == 'audio':
        meta_data = getattr(content_item, 'audiometa', None)
    elif content_item.content_type == 'pdf':
        meta_data = getattr(content_item, 'pdfmeta', None)
    
    context = {
        'content_item': content_item,
        'meta_data': meta_data,
        'available_tags': available_tags,
        'current_language': current_language,
        'current_tags': ','.join([tag.name_ar for tag in content_item.tags.all()]),
    }
    
    return render(request, 'admin/content_detail.html', context)


@require_POST
@login_required
def handle_content_update(request, content_item):
    """Handle content update"""
    try:
        # Update basic fields
        content_item.title_ar = request.POST.get('title_ar', '').strip()
        content_item.title_en = request.POST.get('title_en', '').strip()
        content_item.description_ar = request.POST.get('description_ar', '').strip()
        content_item.description_en = request.POST.get('description_en', '').strip()
        content_item.is_active = 'is_active' in request.POST
        
        content_item.save()
        
        # Update tags
        tags_str = request.POST.get('tags', '').strip()
        if tags_str:
            content_item.tags.clear()
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
            for tag_name in tags:
                tag, created = Tag.objects.get_or_create(
                    name_ar=tag_name,
                    defaults={'name_en': tag_name}
                )
                content_item.tags.add(tag)
        else:
            content_item.tags.clear()
        
        messages.success(request, _('Content updated successfully'))
        
    except Exception as e:
        messages.error(request, f"{_('Update failed')}: {str(e)}")
    
    return redirect('frontend_api:admin_content_detail', content_id=content_item.id)


@login_required
def content_delete_confirm(request, content_id):
    """Confirm content deletion"""
    current_language = get_language()
    content_item = get_object_or_404(ContentItem, id=content_id)
    
    if request.method == 'POST':
        success = content_service.delete_content_item(str(content_item.id))
        if success:
            messages.success(request, _("Content deleted successfully"))
            return redirect('frontend_api:admin_content_list')
        else:
            messages.error(request, _("Failed to delete content"))
            return redirect('frontend_api:admin_content_detail', content_id=content_id)
    
    context = {
        'content_item': content_item,
        'current_language': current_language,
    }
    
    return render(request, 'admin/content_delete_confirm.html', context)


@login_required
def video_management(request):
    """Video-specific management page"""
    current_language = get_language()
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    
    # Get video content with metadata
    queryset = ContentItem.objects.filter(
        content_type='video'
    ).select_related('videometa').prefetch_related('tags')
    
    if search_query:
        queryset = queryset.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query)
        )
    
    paginator = Paginator(queryset, 15)
    videos = paginator.get_page(page)
    
    context = {
        'videos': videos,
        'search_query': search_query,
        'current_language': current_language,
    }
    
    return render(request, 'admin/video_management.html', context)


@login_required
def audio_management(request):
    """Audio-specific management page"""
    current_language = get_language()
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    
    # Get audio content with metadata
    queryset = ContentItem.objects.filter(
        content_type='audio'
    ).select_related('audiometa').prefetch_related('tags')
    
    if search_query:
        queryset = queryset.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query)
        )
    
    paginator = Paginator(queryset, 15)
    audios = paginator.get_page(page)
    
    context = {
        'audios': audios,
        'search_query': search_query,
        'current_language': current_language,
    }
    
    return render(request, 'admin/audio_management.html', context)


@login_required
def pdf_management(request):
    """PDF-specific management page"""
    current_language = get_language()
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    
    # Get PDF content with metadata
    queryset = ContentItem.objects.filter(
        content_type='pdf'
    ).select_related('pdfmeta').prefetch_related('tags')
    
    if search_query:
        queryset = queryset.filter(
            Q(title_ar__icontains=search_query) |
            Q(title_en__icontains=search_query)
        )
    
    paginator = Paginator(queryset, 15)
    pdfs = paginator.get_page(page)
    
    context = {
        'pdfs': pdfs,
        'search_query': search_query,
        'current_language': current_language,
    }
    
    return render(request, 'admin/pdf_management.html', context)


@login_required
def system_monitor(request):
    """System monitoring and maintenance"""
    current_language = get_language()
    
    # Get system statistics
    import os
    import shutil
    from django.conf import settings
    
    # Disk usage
    media_root = settings.MEDIA_ROOT
    disk_usage = shutil.disk_usage(media_root)
    
    # Processing queue
    processing_queue = VideoMeta.objects.filter(
        processing_status__in=['pending', 'processing', 'queued']
    ).count()
    
    # Failed processing
    failed_processing = VideoMeta.objects.filter(
        processing_status='failed'
    ).count()
    
    # File system stats
    def get_directory_size(path):
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(filepath)
        except:
            pass
        return total_size
    
    original_size = get_directory_size(os.path.join(media_root, 'original'))
    compressed_size = get_directory_size(os.path.join(media_root, 'compressed'))
    hls_size = get_directory_size(os.path.join(media_root, 'hls'))
    
    context = {
        'disk_usage': {
            'total': disk_usage.total,
            'used': disk_usage.used,
            'free': disk_usage.free,
            'percentage': round((disk_usage.used / disk_usage.total) * 100, 1)
        },
        'processing_queue': processing_queue,
        'failed_processing': failed_processing,
        'storage_breakdown': {
            'original': original_size,
            'compressed': compressed_size,
            'hls': hls_size,
        },
        'current_language': current_language,
    }
    
    return render(request, 'admin/system_monitor.html', context)


@login_required
def bulk_operations(request):
    """Bulk operations for content management"""
    current_language = get_language()
    
    if request.method == 'POST':
        return handle_bulk_operation(request)
    
    context = {
        'current_language': current_language,
    }
    
    return render(request, 'admin/bulk_operations.html', context)


@require_POST
@login_required
def handle_bulk_operation(request):
    """Handle bulk operations"""
    operation = request.POST.get('operation')
    content_ids = request.POST.getlist('content_ids[]')
    
    if not content_ids:
        messages.error(request, _('Please select content items'))
        return redirect('frontend_api:bulk_operations')
    
    success_count = 0
    error_count = 0
    
    try:
        if operation == 'delete':
            for content_id in content_ids:
                try:
                    content_item = ContentItem.objects.get(id=content_id)
                    success = content_service.delete_content_item(str(content_item.id))
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                except:
                    error_count += 1
        
        elif operation == 'deactivate':
            ContentItem.objects.filter(id__in=content_ids).update(is_active=False)
            success_count = len(content_ids)
        
        elif operation == 'activate':
            ContentItem.objects.filter(id__in=content_ids).update(is_active=True)
            success_count = len(content_ids)
        
        if success_count > 0:
            messages.success(request, f"{_('Operation completed')}: {success_count} {_('items processed')}")
        
        if error_count > 0:
            messages.warning(request, f"{error_count} {_('items failed to process')}")
            
    except Exception as e:
        messages.error(request, f"{_('Bulk operation failed')}: {str(e)}")
    
    return redirect('frontend_api:bulk_operations')


# API endpoints for HTMX/AJAX

@require_http_methods(["POST"])
@csrf_exempt
def api_toggle_content_status(request):
    """Toggle content active status"""
    try:
        data = json.loads(request.body)
        content_id = data.get('content_id')
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        content_item.is_active = not content_item.is_active
        content_item.save()
        
        return JsonResponse({
            'success': True,
            'is_active': content_item.is_active,
            'message': _('Status updated successfully')
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)