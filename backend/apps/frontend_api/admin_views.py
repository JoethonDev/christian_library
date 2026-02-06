"""
Optimized Admin Views for Content Management
Refactored to use AdminService layer and eliminate N+1 queries.
All administrative operations now use minimal database queries.
"""
import json
import os
import tempfile
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django.contrib.auth.decorators import login_required

from apps.media_manager.models import ContentItem, Tag
from apps.media_manager.services.content_service import ContentService
from apps.media_manager.services.upload_service import MediaUploadService
from apps.media_manager.services.delete_service import MediaProcessingService
from apps.media_manager.services.gemini_service import get_gemini_service
from apps.frontend_api.admin_services import AdminService
from core.services.gemini_manager import get_gemini_manager

import logging
import tempfile
import json

logger = logging.getLogger(__name__)

# Initialize services
content_service = ContentService()
admin_service = AdminService()


@login_required
def admin_dashboard(request):
    """Main admin dashboard - Optimized to 4 queries total"""
    # Get all dashboard data with optimized service
    dashboard_data = admin_service.get_dashboard_data()
    
    return render(request, 'admin/dashboard.html', dashboard_data)


@login_required
def content_list(request):
    """List all content - Optimized to 1-2 queries total"""
    # Get filters from request
    content_type = request.GET.get('type', '')
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    
    # Get content list using optimized service
    content_data = admin_service.get_content_list(
        content_type=content_type,
        search_query=search_query,
        page=page,
        per_page=20
    )
    
    context = {
        'content_type': content_type,
        'search_query': search_query,
        'content_data': content_data,
        'current_language': get_language(),
    }
    
    return render(request, 'admin/content_list.html', context)


@login_required
def content_detail(request, content_id):
    """Content detail page - Single optimized query"""
    try:
        # Get content with all relations in single query
        content = admin_service.get_content_detail(str(content_id))
        
        # Handle POST request for status/metadata updates
        if request.method == 'POST':
            # Handle is_active toggle
            if 'toggle_active' in request.POST:
                success, message = admin_service.toggle_content_status(str(content_id))
                if success:
                    messages.success(request, message)
                else:
                    messages.error(request, message)
            else:
                # Handle general metadata updates
                title_ar = request.POST.get('title_ar')
                title_en = request.POST.get('title_en')
                description_ar = request.POST.get('description_ar')
                description_en = request.POST.get('description_en')
                
                content.title_ar = title_ar
                content.title_en = title_en
                content.description_ar = description_ar
                content.description_en = description_en
                content.save(update_fields=['title_ar', 'title_en', 'description_ar', 'description_en', 'updated_at'])
                messages.success(request, _("Sacred metadata updated successfully"))
            
            # Re-fetch content to reflect changes
            content = admin_service.get_content_detail(str(content_id))

        # Process for current language
        processed_content = admin_service.language_processor.process_content_item(
            content, get_language()
        )
        
        context = {
            'content_item': processed_content,
            'meta_data': processed_content.meta,
            'current_language': get_language(),
            'current_tags': ", ".join([t.name_ar for t in processed_content.tags.all()])
        }
        
        return render(request, 'admin/content_detail.html', context)
        
    except ContentItem.DoesNotExist:
        raise Http404(_("Content not found"))


@login_required
def content_delete_confirm(request, content_id):
    """Handle content deletion - Optimized with single query check"""
    try:
        # Get content with all relations in single query
        content = admin_service.get_content_detail(str(content_id))
        
        if request.method == 'POST':
            # Use existing delete service for actual deletion
            processing_service = MediaProcessingService()
            success, message = processing_service.delete_content(content)
            
            if success:
                messages.success(request, message)
                return redirect('frontend_api:admin_content_list')
            else:
                messages.error(request, message)
                return redirect('frontend_api:admin_content_detail', content_id=content_id)
        
        # GET request - Show confirmation page
        # Process for current language
        processed_content = admin_service.language_processor.process_content_item(
            content, get_language()
        )
        
        context = {
            'content_item': processed_content,
            'current_language': get_language(),
        }
        
        return render(request, 'admin/content_delete_confirm.html', context)
            
    except ContentItem.DoesNotExist:
        messages.error(request, _("Content not found"))
        return redirect('frontend_api:admin_content_list')
    except Exception as e:
        messages.error(request, f"Error processing delete request: {str(e)}")
        return redirect('frontend_api:admin_content_detail', content_id=content_id)


@login_required
def upload_content(request):
    """Upload content page"""
    return render(request, 'admin/upload_content.html', {
        'current_language': get_language(),
    })


@login_required
@csrf_exempt
def handle_content_upload(request):
    """Handle content upload using existing service"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        upload_service = MediaUploadService()
        
        # Process upload using existing service
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': 'No file provided'})
        
        # Get metadata from request (all fields from template)
        title_ar = request.POST.get('title_ar', '')
        title_en = request.POST.get('title_en', '')
        description_ar = request.POST.get('description_ar', '')
        description_en = request.POST.get('description_en', '')
        tags = request.POST.get('tags', '').split(',') if request.POST.get('tags') else []
        
        # Get SEO fields from template
        seo_title_en = request.POST.get('seo_title_en', '')
        seo_title_ar = request.POST.get('seo_title_ar', '')
        seo_description_en = request.POST.get('seo_description_en', '')
        seo_description_ar = request.POST.get('seo_description_ar', '')
        seo_keywords_en = request.POST.get('seo_keywords_en', '')
        seo_keywords_ar = request.POST.get('seo_keywords_ar', '')
        transcript = request.POST.get('transcript', '')
        notes = request.POST.get('notes', '')
        seo_structured_data = request.POST.get('seo_structured_data', '')
        
        # Create content item using upload service
        result = upload_service.create_content_item(
            file_obj=file_obj,
            title_ar=title_ar,
            title_en=title_en,
            description_ar=description_ar,
            description_en=description_en,
            tag_ids=tags,
            seo_title_en=seo_title_en,
            seo_title_ar=seo_title_ar,
            seo_description_en=seo_description_en,
            seo_description_ar=seo_description_ar,
            seo_keywords_en=seo_keywords_en,
            seo_keywords_ar=seo_keywords_ar,
            transcript=transcript,
            notes=notes,
            seo_structured_data=seo_structured_data
        )
        
        if result['success']:
            return JsonResponse({
                'success': True,
                'content_id': str(result['content_item'].id),
                'message': 'Content uploaded successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error', 'Upload failed')
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@csrf_exempt
def generate_content_metadata(request):
    """Generate content metadata using Gemini AI"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        content_id = request.POST.get('content_id')
        if not content_id:
            return JsonResponse({'success': False, 'error': 'Content ID required'})
        
        # Get content item
        content = admin_service.get_content_detail(content_id)
        
        # Use Gemini service to generate metadata
        gemini_service = get_gemini_service()
        result = gemini_service.generate_content_metadata(content)
        
        if result['success']:
            # Update content with generated metadata
            content.update_seo_from_gemini(result['metadata'])
            
            return JsonResponse({
                'success': True,
                'message': 'Metadata generated successfully',
                'metadata': result['metadata']
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error', 'Metadata generation failed')
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def video_management(request):
    """Video management page - Optimized queries"""
    page = int(request.GET.get('page', 1))
    filters = {
        'status': request.GET.get('status', ''),
        'processing_status': request.GET.get('processing_status', ''),
        'search': request.GET.get('search', '').strip(),
        'missing_data': request.GET.get('missing_data', '')
    }
    
    # Get video data using optimized service
    video_data = admin_service.get_type_specific_content(
        content_type='video',
        page=page,
        per_page=20,
        filters=filters
    )
    
    context = {
        'content_type': 'video',
        'filters': filters,
        'videos': video_data.get('content_items', []),
        'pagination': video_data.get('pagination'),
        'current_language': get_language(),
    }
    
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/video_table.html', context)
        
    return render(request, 'admin/video_management.html', context)


@login_required
def audio_management(request):
    """Audio management page - Optimized queries"""
    page = int(request.GET.get('page', 1))
    filters = {
        'status': request.GET.get('status', ''),
        'search': request.GET.get('search', '').strip(),
        'missing_data': request.GET.get('missing_data', '')
    }
    
    # Get audio data using optimized service
    audio_data = admin_service.get_type_specific_content(
        content_type='audio',
        page=page,
        per_page=20,
        filters=filters
    )
    
    context = {
        'content_type': 'audio',
        'filters': filters,
        'audios': audio_data.get('content_items', []),
        'pagination': audio_data.get('pagination'),
        'current_language': get_language(),
    }
    
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/audio_table.html', context)
        
    return render(request, 'admin/audio_management.html', context)


@login_required
def pdf_management(request):
    """PDF management page - Optimized queries"""
    page = int(request.GET.get('page', 1))
    filters = {
        'status': request.GET.get('status', ''),
        'search': request.GET.get('search', '').strip(),
        'missing_data': request.GET.get('missing_data', '')
    }
    
    # Get PDF data using optimized service
    pdf_data = admin_service.get_type_specific_content(
        content_type='pdf',
        page=page,
        per_page=20,
        filters=filters
    )
    
    context = {
        'content_type': 'pdf',
        'filters': filters,
        'pdfs': pdf_data.get('content_items', []),
        'pagination': pdf_data.get('pagination'),
        'current_language': get_language(),
    }
    
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/pdf_table.html', context)
        
    return render(request, 'admin/pdf_management.html', context)


@login_required
def system_monitor(request):
    """System monitoring dashboard - Optimized queries"""
    # Get all system data with optimized service
    system_data = admin_service.get_system_monitor_data()
    
    context = {
        **system_data,
        'current_language': get_language(),
    }
    
    return render(request, 'admin/system_monitor.html', context)


@login_required
def bulk_operations(request):
    """Bulk operations page - Optimized queries"""
    if request.method == 'POST':
        operation = request.POST.get('operation')
        # Handle content_ids[] or content_ids (from textarea)
        content_ids_str = request.POST.get('content_ids[]', '') or request.POST.get('content_ids', '')
        
        # Parse IDs (comma or newline separated)
        import re
        content_ids = [cid.strip() for cid in re.split(r'[,\n\r\s]+', content_ids_str) if cid.strip()]
        
        if not content_ids:
            messages.error(request, _("No valid content IDs provided"))
        elif not operation:
            messages.error(request, _("No operation selected"))
        else:
            if operation == 'activate':
                count = ContentItem.objects.filter(id__in=content_ids).update(is_active=True)
                messages.success(request, _(f"Successfully activated {count} items"))
            elif operation == 'deactivate':
                count = ContentItem.objects.filter(id__in=content_ids).update(is_active=False)
                messages.success(request, _(f"Successfully deactivated {count} items"))
            elif operation == 'delete':
                processing_service = MediaProcessingService()
                success_count = 0
                for cid in content_ids:
                    try:
                        # Fetch the content item first as delete_content expects an object
                        content = admin_service.get_content_detail(cid)
                        success, _ = processing_service.delete_content(content)
                        if success:
                            success_count += 1
                    except Exception:
                        pass
                
                if success_count > 0:
                    messages.success(request, _(f"Successfully deleted {success_count} item(s)"))
                if success_count < len(content_ids):
                    messages.warning(request, _(f"Failed to delete some item(s). Check if IDs are correct."))
            
            return redirect('frontend_api:bulk_operations')

    # Get bulk operation data
    bulk_data = admin_service.get_bulk_operation_data()
    
    context = {
        'bulk_stats': bulk_data,
        'current_language': get_language(),
    }
    
    return render(request, 'admin/bulk_operations.html', context)


@login_required
@require_http_methods(["POST"])
def api_toggle_content_status(request):
    """API endpoint to toggle content status - Supports single and bulk operations"""
    try:
        data = json.loads(request.body)
        content_id = data.get('content_id')
        content_ids = data.get('content_ids')
        is_bulk = data.get('bulk', False)
        target_status = data.get('is_active', True)
        
        # Handle bulk operation
        if is_bulk and content_ids:
            updated_count = ContentItem.objects.filter(
                id__in=content_ids
            ).update(is_active=target_status)
            
            status_text = _("activated") if target_status else _("deactivated")
            message = _("%(count)s item(s) %(status)s") % {
                'count': updated_count,
                'status': status_text
            }
            return JsonResponse({
                'success': True,
                'message': message,
                'updated_count': updated_count
            })
        
        # Handle single operation
        if not content_id:
            return JsonResponse({'success': False, 'error': 'Content ID required'})
        
        # Toggle status using optimized service
        success, message = admin_service.toggle_content_status(content_id)
        
        return JsonResponse({
            'success': success,
            'message': message
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# Bulk operation API endpoints
@login_required
@require_POST
@csrf_exempt
def api_bulk_generate_seo(request):
    """Bulk SEO generation API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': 'No content IDs provided'})
        
        # Process each content item
        results = []
        gemini_service = get_gemini_service()
        
        for content_id in content_ids:
            try:
                content = admin_service.get_content_detail(content_id)
                result = gemini_service.generate_content_metadata(content)
                
                if result['success']:
                    content.update_seo_from_gemini(result['metadata'])
                    results.append({'id': content_id, 'success': True})
                else:
                    results.append({'id': content_id, 'success': False, 'error': result.get('error')})
                    
            except Exception as e:
                results.append({'id': content_id, 'success': False, 'error': str(e)})
        
        success_count = sum(1 for r in results if r['success'])
        
        return JsonResponse({
            'success': True,
            'message': f'SEO metadata generated for {success_count}/{len(content_ids)} items',
            'results': results
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
@csrf_exempt
def api_bulk_toggle_status(request):
    """Bulk status toggle API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        target_status = data.get('status', True)  # True for active, False for inactive
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': 'No content IDs provided'})
        
        # Bulk update using single query
        updated_count = ContentItem.objects.filter(
            id__in=content_ids
        ).update(is_active=target_status)
        
        status_text = "active" if target_status else "inactive"
        
        return JsonResponse({
            'success': True,
            'message': f'{updated_count} items set to {status_text}',
            'updated_count': updated_count
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
@csrf_exempt
def api_bulk_delete(request):
    """Bulk delete API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': 'No content IDs provided'})
        
        # Use processing service for proper deletion
        processing_service = MediaProcessingService()
        results = []
        
        for content_id in content_ids:
            try:
                # Use admin_service to get the object with relations
                content = admin_service.get_content_detail(content_id)
                success, message = processing_service.delete_content(content)
                results.append({
                    'id': content_id,
                    'success': success,
                    'message': message
                })
            except ContentItem.DoesNotExist:
                results.append({
                    'id': content_id,
                    'success': False,
                    'message': 'Content not found'
                })
            except Exception as e:
                results.append({
                    'id': content_id,
                    'success': False,
                    'message': str(e)
                })
        
        success_count = sum(1 for r in results if r['success'])
        
        return JsonResponse({
            'success': True,
            'message': f'{success_count}/{len(content_ids)} items deleted successfully',
            'results': results
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@csrf_exempt
def generate_metadata_from_file(request):
    """Generate metadata from uploaded file (before content creation)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': 'File required'})
        
        # Get content type from file or request
        content_type = request.POST.get('content_type', '')
        if not content_type:
            # Determine content type from file extension
            file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else ''
            if file_extension in ['mp4', 'avi', 'mov', 'mkv']:
                content_type = 'video'
            elif file_extension in ['mp3', 'wav', 'flac', 'm4a']:
                content_type = 'audio'
            elif file_extension in ['pdf']:
                content_type = 'pdf'
            else:
                return JsonResponse({'success': False, 'error': 'Unsupported file type'})
        
        # Use Gemini service to generate metadata from file
        gemini_service = get_gemini_service()
        if not gemini_service.is_available():
            return JsonResponse({'success': False, 'error': 'AI service not available'})
        
        # Save file temporarily for processing
        import tempfile
        import os
        file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else 'tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        try:
            # Generate metadata using the temporary file
            success, metadata = gemini_service.generate_seo_metadata(temp_file_path, content_type)
            
            if success and metadata:
                return JsonResponse({
                    'success': True,
                    'metadata': metadata
                })
            else:
                error_msg = metadata.get('error', 'Failed to generate metadata') if isinstance(metadata, dict) else 'Failed to generate metadata'
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_r2_storage_usage(request):
    """
    Get R2 bucket storage usage statistics for admin dashboard.
    Returns cached data by default (5 minute cache).
    Use ?refresh=true to force refresh.
    """
    try:
        from core.services.r2_storage_service import get_r2_storage_service
        
        # Check if user has permission (staff or superuser)
        if not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied. Staff access required.'
            }, status=403)
        
        # Get R2 storage service
        r2_service = get_r2_storage_service()
        
        # Check if refresh is requested
        refresh = request.GET.get('refresh', 'false').lower() == 'true'
        use_cache = not refresh
        
        # Get bucket usage
        usage_data = r2_service.get_bucket_usage(use_cache=use_cache)
        
        return JsonResponse(usage_data)
        
    except Exception as e:
        print(f"Error fetching R2 storage usage: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'total_size_bytes': 0,
            'total_size_gb': 0.0,
            'object_count': 0
        })


@login_required
@require_POST
@csrf_exempt
def api_auto_fill_metadata(request):
    """
    Trigger auto-fill action for content item(s) (SEO metadata generation).
    Supports both single and bulk operations.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        data = json.loads(request.body)
        content_id = data.get('content_id')
        content_ids = data.get('content_ids')
        
        # Handle bulk operation
        if content_ids:
            from apps.media_manager.tasks import generate_seo_metadata_task
            
            task_ids = []
            success_count = 0
            
            for cid in content_ids:
                try:
                    # Verify content exists
                    content = ContentItem.objects.get(id=cid)
                    task = generate_seo_metadata_task.delay(str(cid))
                    task_ids.append(task.id)
                    success_count += 1
                except ContentItem.DoesNotExist:
                    logger.warning(f"Content {cid} not found for bulk SEO generation")
                    continue
            
            logger.info(f"Bulk auto-fill triggered for {success_count} items")
            
            return JsonResponse({
                'success': True,
                'message': f'SEO generation started for {success_count} item(s)',
                'task_ids': task_ids
            })
        
        # Handle single operation
        if not content_id:
            return JsonResponse({'success': False, 'error': 'No content ID provided'})
        
        # Get the content item
        try:
            content = ContentItem.objects.get(id=content_id)
        except ContentItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Content not found'})
        
        # Import the task
        from apps.media_manager.tasks import generate_seo_metadata_task
        
        # Trigger the background task
        task = generate_seo_metadata_task.delay(str(content_id))
        
        logger.info(f"Auto-fill triggered for content {content_id}, task ID: {task.id}")
        
        return JsonResponse({
            'success': True,
            'message': 'Auto-fill started. SEO metadata will be generated in the background.',
            'task_id': task.id
        })
        
    except Exception as e:
        logger.error(f"Error triggering auto-fill: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})



def _save_uploaded_file_temporarily(file_obj):
    """Helper function to save uploaded file temporarily and return its path"""
    file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else 'tmp'
    with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
        for chunk in file_obj.chunks():
            temp_file.write(chunk)
        return temp_file.name


def _cleanup_temp_file(file_path):
    """Helper function to clean up temporary file with proper error handling"""
    try:
        os.unlink(file_path)
    except OSError as e:
        logger.warning(f"Failed to clean up temporary file {file_path}: {e}")


def _determine_content_type(file_obj, content_type_param):
    """Helper function to determine content type from file or parameter"""
    if content_type_param:
        return content_type_param, None
    
    # Determine content type from file extension
    file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else ''
    if file_extension in ['mp4', 'avi', 'mov', 'mkv']:
        return 'video', None
    elif file_extension in ['mp3', 'wav', 'flac', 'm4a']:
        return 'audio', None
    elif file_extension in ['pdf']:
        return 'pdf', None
    else:
        return None, 'Unsupported file type'


def generate_metadata_only(request):
    """Generate metadata only from uploaded file (new separated endpoint)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        from core.services.gemini_metadata_service import get_gemini_metadata_service
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': 'File required'})
        
        # Determine content type
        content_type, error = _determine_content_type(file_obj, request.POST.get('content_type', ''))
        if error:
            return JsonResponse({'success': False, 'error': error})
        
        # Use Gemini metadata service
        metadata_service = get_gemini_metadata_service()
        if not metadata_service.is_available():
            return JsonResponse({'success': False, 'error': 'AI service not available'})
        
        # Save file temporarily for processing
        temp_file_path = _save_uploaded_file_temporarily(file_obj)
        
        try:
            # Generate metadata using the temporary file
            success, metadata = metadata_service.generate_metadata(temp_file_path, content_type)
            
            if success and metadata:
                return JsonResponse({
                    'success': True,
                    'metadata': metadata
                })
            else:
                error_msg = metadata.get('error', 'Failed to generate metadata') if isinstance(metadata, dict) else 'Failed to generate metadata'
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            _cleanup_temp_file(temp_file_path)
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def generate_seo_only(request):
    """Generate SEO metadata only from uploaded file (new separated endpoint)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        from core.services.gemini_seo_service import get_gemini_seo_service
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': 'File required'})
        
        # Determine content type
        content_type, error = _determine_content_type(file_obj, request.POST.get('content_type', ''))
        if error:
            return JsonResponse({'success': False, 'error': error})
        
        # Use Gemini SEO service
        seo_service = get_gemini_seo_service()
        if not seo_service.is_available():
            return JsonResponse({'success': False, 'error': 'AI service not available'})
        
        # Save file temporarily for processing
        temp_file_path = _save_uploaded_file_temporarily(file_obj)
        
        try:
            # Generate SEO metadata using the temporary file
            success, seo_data = seo_service.generate_seo(temp_file_path, content_type)
            
            if success and seo_data:
                return JsonResponse({
                    'success': True,
                    'seo': seo_data
                })
            else:
                error_msg = seo_data.get('error', 'Failed to generate SEO metadata') if isinstance(seo_data, dict) else 'Failed to generate SEO metadata'
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            _cleanup_temp_file(temp_file_path)
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
def api_content_seo(request, content_id):
    """API endpoint to get or update SEO metadata for a content item"""
    try:
        content = get_object_or_404(ContentItem, id=content_id)
        
        if request.method == 'GET':
            # Return current SEO data
            return JsonResponse({
                'success': True,
                'seo_title_en': content.seo_title_en or '',
                'seo_title_ar': content.seo_title_ar or '',
                'seo_meta_description_en': content.seo_meta_description_en or '',
                'seo_meta_description_ar': content.seo_meta_description_ar or '',
                'seo_keywords_en': content.seo_keywords_en or '',
                'seo_keywords_ar': content.seo_keywords_ar or '',
                'structured_data': json.dumps(content.structured_data) if content.structured_data else '{}',
                'transcript': content.transcript or '',
                'notes': content.notes or ''
            })
        
        elif request.method == 'POST':
            # Update SEO data
            data = json.loads(request.body)
            
            content.seo_title_en = data.get('seo_title_en', '')[:70]
            content.seo_title_ar = data.get('seo_title_ar', '')[:70]
            content.seo_meta_description_en = data.get('seo_meta_description_en', '')[:160]
            content.seo_meta_description_ar = data.get('seo_meta_description_ar', '')[:160]
            content.seo_keywords_en = data.get('seo_keywords_en', '')
            content.seo_keywords_ar = data.get('seo_keywords_ar', '')
            content.transcript = data.get('transcript', '')
            content.notes = data.get('notes', '')
            
            # Validate and save structured data
            structured_data = data.get('structured_data', '')
            if structured_data:
                try:
                    # Validate it's valid JSON and store as dict
                    content.structured_data = json.loads(structured_data)
                except json.JSONDecodeError:
                    return JsonResponse({'success': False, 'error': 'Invalid JSON in structured data'})
            
            content.save()
            
            return JsonResponse({
                'success': True,
                'message': 'SEO data updated successfully'
            })
        
        else:
            return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def api_gemini_rate_limits(request):
    """API endpoint to get Gemini rate limit information"""
    try:
        gemini_manager = get_gemini_manager()
        
        # Check if force refresh requested
        force_refresh = request.GET.get('refresh', 'false').lower() == 'true'
        
        if force_refresh:
            rate_limits = gemini_manager.refresh_rate_limits()
        else:
            rate_limits = gemini_manager.get_rate_limit_status()
        
        # Check availability
        metadata_available, metadata_msg = gemini_manager.check_metadata_availability()
        seo_available, seo_msg = gemini_manager.check_seo_availability()
        
        return JsonResponse({
            'success': True,
            'rate_limits': rate_limits,
            'metadata_available': metadata_available,
            'metadata_message': metadata_msg,
            'seo_available': seo_available,
            'seo_message': seo_msg,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def analytics_dashboard(request):
    """
    Analytics dashboard showing content viewing statistics.
    Displays charts and tables for content view analytics.
    Includes historical summaries and real-time events for today.
    Shows both total views and unique views (by IP).
    """
    from datetime import timedelta, date
    from django.db.models import Sum, Count
    from django.utils import timezone
    from apps.media_manager.models import DailyContentViewSummary, ContentViewEvent, ContentItem
    
    try:
        # Date range (last 30 days by default)
        days = int(request.GET.get('days', 30))
        end_date = date.today()
        start_date = end_date - timedelta(days=days-1)
        
        # 1. Historical Data from summaries
        summaries = DailyContentViewSummary.objects.filter(
            date__range=(start_date, end_date)
        )
        
        # Daily stats by content type (historical) - convert dates to strings
        daily_stats_list = []
        for stat in summaries.values('content_type', 'date').annotate(
            total_views=Sum('view_count'),
            unique_views=Sum('unique_view_count')
        ).order_by('date', 'content_type'):
            daily_stats_list.append({
                'content_type': stat['content_type'],
                'date': stat['date'].isoformat(),  # Convert date to ISO string
                'total_views': stat['total_views'],
                'unique_views': stat['unique_views']
            })

        # 2. Real-time Data for today from events
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_events = ContentViewEvent.objects.filter(timestamp__gte=today_start)
        
        today_stats = today_events.values('content_type').annotate(
            total_views=Count('id')
        )
        
        # Calculate unique views for today (distinct IPs per content type)
        today_unique_stats = {}
        for content_type in ['video', 'audio', 'pdf', 'static']:
            unique_count = today_events.filter(
                content_type=content_type
            ).values('ip_address').distinct().count()
            if unique_count > 0:
                today_unique_stats[content_type] = unique_count
        
        # Add today's stats to daily_stats_list
        for stat in today_stats:
            daily_stats_list.append({
                'content_type': stat['content_type'],
                'date': end_date.isoformat(),  # Convert date to ISO string
                'total_views': stat['total_views'],
                'unique_views': today_unique_stats.get(stat['content_type'], 0)
            })
        
        # Sort combined list by date and content_type
        daily_stats_list.sort(key=lambda x: (x['date'], x['content_type']))
        
        # 3. Combine top content from summaries and today's events
        # Get historical IDs and counts
        hist_top_qs = summaries.values('content_type', 'content_id').annotate(
            total_views=Sum('view_count'),
            unique_views=Sum('unique_view_count')
        )
        hist_top = { 
            (item['content_type'], str(item['content_id'])): {
                'total_views': item['total_views'],
                'unique_views': item['unique_views']
            }
            for item in hist_top_qs 
        }
        
        # Get today's counts
        today_top_qs = today_events.values('content_type', 'content_id').annotate(total_views=Count('id'))
        
        # Combine
        combined_top_map = hist_top.copy()
        for item in today_top_qs:
            key = (item['content_type'], str(item['content_id']))
            # Count unique IPs for this content today
            unique_today = today_events.filter(
                content_type=item['content_type'],
                content_id=item['content_id']
            ).values('ip_address').distinct().count()
            
            if key in combined_top_map:
                combined_top_map[key]['total_views'] += item['total_views']
                combined_top_map[key]['unique_views'] += unique_today
            else:
                combined_top_map[key] = {
                    'total_views': item['total_views'],
                    'unique_views': unique_today
                }
        
        # Convert back to list and sort
        top_content = [
            {
                'content_type': k[0], 
                'content_id': k[1], 
                'total_views': v['total_views'],
                'unique_views': v['unique_views']
            }
            for k, v in combined_top_map.items()
        ]
        top_content.sort(key=lambda x: x['total_views'], reverse=True)
        top_content = top_content[:20]
        
        # Fetch ContentItem titles for top content
        content_ids = [item['content_id'] for item in top_content]
        content_map = {
            str(c.id): c 
            for c in ContentItem.objects.filter(id__in=content_ids).only('id', 'title_ar', 'title_en', 'content_type')
        }
        
        # Add titles to top content items
        for item in top_content:
            content_id = str(item['content_id'])
            if content_id in content_map:
                content = content_map[content_id]
                item['title'] = content.title_ar or content.title_en or 'Unknown'
                item['content_object'] = content
            else:
                item['title'] = 'Unknown (Deleted)'
                item['content_object'] = None
        
        # 4. Calculate totals by content type (combined)
        combined_totals_map = {}
        for t in summaries.values('content_type').annotate(
            total_views=Sum('view_count'),
            unique_views=Sum('unique_view_count')
        ):
            combined_totals_map[t['content_type']] = {
                'total_views': t['total_views'],
                'unique_views': t['unique_views']
            }
        
        for t in today_stats:
            content_type = t['content_type']
            if content_type in combined_totals_map:
                combined_totals_map[content_type]['total_views'] += t['total_views']
                combined_totals_map[content_type]['unique_views'] += today_unique_stats.get(content_type, 0)
            else:
                combined_totals_map[content_type] = {
                    'total_views': t['total_views'],
                    'unique_views': today_unique_stats.get(content_type, 0)
                }
            
        totals_by_type = [
            {
                'content_type': k, 
                'total_views': v['total_views'],
                'unique_views': v['unique_views']
            }
            for k, v in combined_totals_map.items()
        ]
        totals_by_type.sort(key=lambda x: x['total_views'], reverse=True)
        
        # Overall totals
        total_views = sum(t['total_views'] for t in totals_by_type)
        total_unique_views = sum(t['unique_views'] for t in totals_by_type)
        
        # Content item counts (distinct IDs across both)
        hist_ids = set(summaries.values_list('content_id', flat=True).distinct())
        today_ids = set(today_events.values_list('content_id', flat=True).distinct())
        total_content_items = len(hist_ids | today_ids)
        
        context = {
            'daily_stats': daily_stats_list,
            'top_content': top_content,
            'totals_by_type': totals_by_type,
            'total_views': total_views,
            'total_unique_views': total_unique_views,
            'total_content_items': total_content_items,
            'start_date': start_date,
            'end_date': end_date,
            'days': days,
        }
        
        return render(request, 'admin/analytics_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in analytics_dashboard: {str(e)}", exc_info=True)
        return render(request, 'admin/analytics_dashboard.html', {
            'error': str(e),
            'daily_stats': [],
            'top_content': [],
            'totals_by_type': [],
            'total_views': 0,
            'total_unique_views': 0,
            'total_content_items': 0,
        })


@login_required
def api_analytics_views(request):
    """
    API endpoint for analytics data in JSON format.
    Used for AJAX requests and chart rendering.
    Includes historical summaries and real-time events for today.
    """
    from datetime import timedelta, date
    from django.db.models import Sum, Count
    from django.utils import timezone
    from apps.media_manager.models import DailyContentViewSummary, ContentViewEvent
    
    try:
        # Date range parameters
        days = int(request.GET.get('days', 30))
        content_type = request.GET.get('content_type', None)
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days-1)
        
        # 1. Historical Data
        queryset = DailyContentViewSummary.objects.filter(
            date__range=(start_date, end_date)
        )
        
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        
        # Aggregate by date and content type
        stats = queryset.values('content_type', 'date').annotate(
            total_views=Sum('view_count')
        ).order_by('date')
        
        # Format for response
        data = []
        for stat in stats:
            data.append({
                'content_type': stat['content_type'],
                'date': stat['date'].isoformat(),
                'total_views': stat['total_views']
            })
            
        # 2. Real-time Data for today (if within range)
        if end_date >= start_date:
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_queryset = ContentViewEvent.objects.filter(timestamp__gte=today_start)
            
            if content_type:
                today_queryset = today_queryset.filter(content_type=content_type)
                
            today_stats = today_queryset.values('content_type').annotate(
                total_views=Count('id')
            )
            
            for stat in today_stats:
                data.append({
                    'content_type': stat['content_type'],
                    'date': end_date.isoformat(),
                    'total_views': stat['total_views']
                })
        
        # Sort data by date
        data.sort(key=lambda x: x['date'])
        
        return JsonResponse({
            'success': True,
            'data': data,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        })
        
    except Exception as e:
        logger.error(f"Error in api_analytics_views: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
