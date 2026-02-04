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
        'search': request.GET.get('search', '').strip()
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
    
    return render(request, 'admin/video_management.html', context)


@login_required
def audio_management(request):
    """Audio management page - Optimized queries"""
    page = int(request.GET.get('page', 1))
    filters = {
        'status': request.GET.get('status', ''),
        'search': request.GET.get('search', '').strip()
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
    
    return render(request, 'admin/audio_management.html', context)


@login_required
def pdf_management(request):
    """PDF management page - Optimized queries"""
    page = int(request.GET.get('page', 1))
    filters = {
        'status': request.GET.get('status', ''),
        'search': request.GET.get('search', '').strip()
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
    """API endpoint to toggle content status - Single query"""
    try:
        data = json.loads(request.body)
        content_id = data.get('content_id')
        
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
        logger.error(f"Error fetching R2 storage usage: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'total_size_bytes': 0,
            'total_size_gb': 0.0,
            'object_count': 0
        })


def generate_metadata_only(request):
    """Generate metadata only from uploaded file (new separated endpoint)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        from core.services.gemini_metadata_service import get_gemini_metadata_service
        
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
        
        # Use Gemini metadata service
        metadata_service = get_gemini_metadata_service()
        if not metadata_service.is_available():
            return JsonResponse({'success': False, 'error': 'AI service not available'})
        
        # Save file temporarily for processing
        file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else 'tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
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
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except OSError as e:
                # Log cleanup failure but don't fail the request
                logger.warning(f"Failed to clean up temporary file {temp_file_path}: {e}")
                
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
        
        # Use Gemini SEO service
        seo_service = get_gemini_seo_service()
        if not seo_service.is_available():
            return JsonResponse({'success': False, 'error': 'AI service not available'})
        
        # Save file temporarily for processing
        file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else 'tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
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
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except OSError as e:
                # Log cleanup failure but don't fail the request
                logger.warning(f"Failed to clean up temporary file {temp_file_path}: {e}")
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

