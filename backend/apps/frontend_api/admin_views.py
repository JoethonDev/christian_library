"""
Admin Views for Content Management
Handles all administrative operations with full RTL/LTR and localization support
"""
import json
import os
import tempfile
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django.contrib.auth.decorators import login_required

from apps.media_manager.models import ContentItem, VideoMeta, Tag
from apps.media_manager.services.content_service import ContentService
from apps.media_manager.services.upload_service import MediaUploadService
from apps.media_manager.services.delete_service import MediaProcessingService
from apps.media_manager.services.gemini_service import get_gemini_service
import json
import tempfile
import os


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
        'number': content_page.number,
        'num_pages': paginator.num_pages,
        'has_previous': content_page.has_previous(),
        'has_next': content_page.has_next(),
        'has_pagination': paginator.num_pages > 1,
    }
    
    if content_page.has_previous():
        content_data['previous_page_number'] = content_page.previous_page_number()
    
    if content_page.has_next():
        content_data['next_page_number'] = content_page.next_page_number()
        
    # Add pagination indexes for display
    content_data['start_index'] = (content_page.number - 1) * 20 + 1
    content_data['end_index'] = min(content_page.number * 20, paginator.count)
    
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
    # Check if this is an AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    try:
        # Extract form data
        title_ar = request.POST.get('title_ar', '').strip()
        title_en = request.POST.get('title_en', '').strip()
        description_ar = request.POST.get('description_ar', '').strip()
        description_en = request.POST.get('description_en', '').strip()
        content_type = request.POST.get('content_type', 'video')
        tags_str = request.POST.get('tags', '').strip()
        
        # Extract SEO metadata
        seo_keywords_ar = request.POST.get('seo_keywords_ar', '').strip()
        seo_keywords_en = request.POST.get('seo_keywords_en', '').strip()
        seo_meta_description_ar = request.POST.get('seo_meta_description_ar', '').strip()
        seo_meta_description_en = request.POST.get('seo_meta_description_en', '').strip()
        seo_title_suggestions = request.POST.get('seo_title_suggestions', '').strip()
        structured_data = request.POST.get('structured_data', '').strip()
        
        # Validate required fields
        if not title_ar:
            error_msg = str(_('Arabic title is required'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('frontend_api:upload_content')
        
        if 'file' not in request.FILES:
            error_msg = str(_('Please select a file to upload'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
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
            error_msg = str(_('Invalid file type for selected content type'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('frontend_api:upload_content')
        
        # Process tags - convert tag names to tag IDs
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
        tag_ids = []
        if tags:
            from ..media_manager.models import Tag
            for tag_name in tags:
                tag_name = tag_name.strip()
                if tag_name:
                    tag, created = Tag.objects.get_or_create(
                        name_ar=tag_name,
                        defaults={'name_en': tag_name, 'is_active': True, 'color': '#B8860B'}
                    )
                    tag_ids.append(str(tag.id))
        
        # Upload based on content type
        if content_type == 'video':
            success, message, content_item = MediaUploadService.upload_video(
                file, title_ar, title_en, description_ar, description_en, tag_ids,
                seo_keywords_ar, seo_keywords_en, seo_meta_description_ar, 
                seo_meta_description_en, seo_title_suggestions, structured_data
            )
        elif content_type == 'audio':
            success, message, content_item = MediaUploadService.upload_audio(
                file, title_ar, description_ar, title_en, description_en, tag_ids,
                seo_keywords_ar, seo_keywords_en, seo_meta_description_ar, 
                seo_meta_description_en, seo_title_suggestions, structured_data
            )
        elif content_type == 'pdf':
            success, message, content_item = MediaUploadService.upload_pdf(
                file, title_ar, description_ar, title_en, description_en, tag_ids,
                seo_keywords_ar, seo_keywords_en, seo_meta_description_ar, 
                seo_meta_description_en, seo_title_suggestions, structured_data
            )
        else:
            error_msg = str(_('Invalid content type'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('frontend_api:upload_content')
        
        if success:
            if is_ajax:
                return JsonResponse({
                    'success': True, 
                    'message': str(message),
                    'redirect_url': f'/admin/content/{content_item.id}/'
                })
            messages.success(request, message)
            return redirect('frontend_api:admin_content_detail', content_id=content_item.id)
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(message)})
            messages.error(request, message)
            
    except Exception as e:
        error_msg = f"{str(_('Upload failed'))}: {str(e)}"
        if is_ajax:
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
    
    if is_ajax:
        return JsonResponse({'success': False, 'error': str(_('Unknown error occurred'))})
    return redirect('frontend_api:upload_content')


@login_required
@require_POST  
def generate_content_metadata(request):
    """Generate complete content and SEO metadata using Gemini AI"""
    try:
        # Get uploaded file from request
        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'error': _('No file provided')})
            
        file = request.FILES['file']
        content_type = request.POST.get('content_type', '')
        
        if not content_type or content_type not in ['video', 'audio', 'pdf']:
            return JsonResponse({'success': False, 'error': _('Invalid content type')})
        
        # Validate file type
        valid_extensions = {
            'video': ['.mp4', '.avi', '.mov', '.mkv', '.wmv'],
            'audio': ['.mp3', '.wav', '.flac', '.aac', '.ogg'],
            'pdf': ['.pdf']
        }
        
        file_ext = file.name.lower().split('.')[-1]
        if f'.{file_ext}' not in valid_extensions.get(content_type, []):
            return JsonResponse({'success': False, 'error': _('Invalid file type for selected content type')})
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as temp_file:
            for chunk in file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        try:
            # Get Gemini service and generate complete metadata
            gemini_service = get_gemini_service()
            
            if not gemini_service.is_available():
                return JsonResponse({
                    'success': False, 
                    'error': _('AI service is not available. Please try again later.')
                })
            
            success, metadata = gemini_service.generate_complete_metadata(temp_file_path, content_type)
            
            if success:
                return JsonResponse({
                    'success': True,
                    'metadata': metadata
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': metadata.get('error', _('AI generation failed'))
                })
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"{_('Generation failed')}: {str(e)}"})


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
                    defaults={'name_en': tag_name, 'is_active': True}
                )
                content_item.tags.add(tag)
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
        media_service = MediaProcessingService()
        success, msg = media_service.delete_content(content_item)
        if success:
            return redirect('frontend_api:admin_content_list')
        else:
            messages.error(request, msg)
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
    
    # Get all content for bulk operations
    content_items = ContentItem.objects.filter(is_active=True).prefetch_related('tags')
    
    context = {
        'content_items': content_items,
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
        if operation == 'activate':
            updated = ContentItem.objects.filter(id__in=content_ids).update(is_active=True)
            success_count = updated
            messages.success(request, f'Activated {success_count} items')
            
        elif operation == 'deactivate':
            updated = ContentItem.objects.filter(id__in=content_ids).update(is_active=False)
            success_count = updated
            messages.success(request, f'Deactivated {success_count} items')
            
        elif operation == 'delete':
            # Soft delete by marking as inactive
            updated = ContentItem.objects.filter(id__in=content_ids).update(is_active=False)
            success_count = updated
            messages.success(request, f'Deleted {success_count} items')
            
        else:
            messages.error(request, _('Invalid operation'))
            
    except Exception as e:
        messages.error(request, f'Operation failed: {str(e)}')
    
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