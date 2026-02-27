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
from apps.media_manager.services.search_settings_service import get_search_settings_service
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
                notes = request.POST.get('notes', '')
                transcript = request.POST.get('transcript', '')
                seo_title_ar = request.POST.get('seo_title_ar', '')
                seo_title_en = request.POST.get('seo_title_en', '')
                tags_input = request.POST.get('tags', '')
                thumbnail_file = request.FILES.get('thumbnail')
                
                # Update basic fields
                content.title_ar = title_ar
                content.title_en = title_en
                content.description_ar = description_ar
                content.description_en = description_en
                content.notes = notes
                content.transcript = transcript
                content.seo_title_ar = seo_title_ar
                content.seo_title_en = seo_title_en
                
                update_fields = [
                    'title_ar', 'title_en', 'description_ar', 'description_en',
                    'notes', 'transcript', 'seo_title_ar', 'seo_title_en', 'updated_at'
                ]
                
                if thumbnail_file:
                    content.thumbnail = thumbnail_file
                    update_fields.append('thumbnail')
                
                content.save(update_fields=update_fields)
                
                # Handle tags - parse comma-separated tag names
                if tags_input:
                    tag_names = [name.strip() for name in tags_input.split(',') if name.strip()]
                    tag_objects = []
                    
                    for tag_name in tag_names:
                        # Try to find existing tag by Arabic name
                        tag = Tag.objects.filter(name_ar=tag_name, is_active=True).first()
                        if tag:
                            tag_objects.append(tag)
                        else:
                            # Create new tag if it doesn't exist
                            try:
                                tag = Tag.objects.create(name_ar=tag_name, is_active=True)
                                tag_objects.append(tag)
                                logger.info(f"Created new tag: {tag_name}")
                            except Exception as e:
                                logger.warning(f"Could not create tag '{tag_name}': {e}")
                    
                    # Update the tags relationship
                    content.tags.set(tag_objects)
                    logger.info(f"Updated tags for content {content_id}: {tag_names}")
                
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
def delete_local_confirm(request, content_id):
    """Handle local file deletion only, preserving R2 and DB record."""
    try:
        content = admin_service.get_content_detail(str(content_id))
        
        # Get meta object based on content type
        meta = None
        if content.content_type == 'video':
            meta = getattr(content, 'videometa', None)
        elif content.content_type == 'audio':
            meta = getattr(content, 'audiometa', None)
        elif content.content_type == 'pdf':
            meta = getattr(content, 'pdfmeta', None)
            
        if request.method == 'POST':
            processing_service = MediaProcessingService()
            success, message = processing_service.delete_local_file_only(content)
            
            if success:
                messages.success(request, message)
                # Redirect to management list based on type
                if content.content_type == 'video':
                    return redirect('frontend_api:video_management')
                elif content.content_type == 'audio':
                    return redirect('frontend_api:audio_management')
                elif content.content_type == 'pdf':
                    return redirect('frontend_api:pdf_management')
                return redirect('frontend_api:admin_content_list')
            else:
                messages.error(request, message)
                return redirect('frontend_api:admin_content_detail', content_id=content_id)

        # GET request - Show confirmation page
        processed_content = admin_service.language_processor.process_content_item(
            content, get_language()
        )
        
        context = {
            'content_item': processed_content,
            'meta': meta,
            'current_language': get_language(),
        }
        
        return render(request, 'admin/delete_local_confirm.html', context)
            
    except ContentItem.DoesNotExist:
        messages.error(request, _("Content not found"))
        return redirect('frontend_api:admin_content_list')
    except Exception as e:
        messages.error(request, f"Error processing request: {str(e)}")
        return redirect('frontend_api:admin_content_list')


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
        
        # Get document file if provided
        document_file = request.FILES.get('document')
        
        # Get thumbnail file if provided
        thumbnail_file = request.FILES.get('thumbnail_file')
        
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
            seo_structured_data=seo_structured_data,
            document_file=document_file,  # Pass document file
            thumbnail_file=thumbnail_file  # Pass thumbnail file
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
        
        # Get the updated status to return to frontend
        if success:
            try:
                content = ContentItem.objects.only('is_active').get(id=content_id)
                return JsonResponse({
                    'success': True,
                    'message': message,
                    'is_active': content.is_active
                })
            except ContentItem.DoesNotExist:
                pass
        
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
def r2_status_dashboard(request):
    """
    R2 Upload Status Dashboard - Shows detailed R2 upload status for all content items.
    Provides retry functionality and bulk operations for failed uploads.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta
        from django.db.models import Q
        
        # Get filter parameters
        status_filter = request.GET.get('status', 'all')  # all, pending, uploading, completed, failed
        content_type = request.GET.get('type', 'all')  # all, video, audio, pdf
        
        # Build status data
        status_data = {}
        
        # Video content R2 status
        if content_type in ['all', 'video']:
            video_queryset = VideoMeta.objects.select_related('content_item').only(
                'id', 'r2_upload_status', 'r2_upload_progress', 
                'content_item__title_ar', 'content_item__created_at',
                'content_item__id'
            )
            if status_filter == 'all':
                # Show only failed and pending items by default
                video_queryset = video_queryset.filter(
                    Q(r2_upload_status='failed') | Q(r2_upload_status='pending') | 
                    Q(r2_upload_status='') | Q(r2_upload_status__isnull=True)
                )
            else:
                video_queryset = video_queryset.filter(r2_upload_status=status_filter)
            
            status_data['videos'] = [
                {
                    'id': vm.id,
                    'content_id': vm.content_item.id,
                    'title': vm.content_item.title_ar,
                    'status': vm.r2_upload_status or 'pending',
                    'progress': vm.r2_upload_progress or 0,
                    'created_at': vm.content_item.created_at.isoformat(),
                    'type': 'video'
                }
                for vm in video_queryset[:100]  # Limit to 100 items
            ]
        
        # Audio content R2 status  
        if content_type in ['all', 'audio']:
            audio_queryset = AudioMeta.objects.select_related('content_item').only(
                'id', 'r2_upload_status', 'r2_upload_progress',
                'content_item__title_ar', 'content_item__created_at',
                'content_item__id'
            )
            if status_filter == 'all':
                # Show only failed and pending items by default
                audio_queryset = audio_queryset.filter(
                    Q(r2_upload_status='failed') | Q(r2_upload_status='pending') | 
                    Q(r2_upload_status='') | Q(r2_upload_status__isnull=True)
                )
            else:
                audio_queryset = audio_queryset.filter(r2_upload_status=status_filter)
            
            status_data['audios'] = [
                {
                    'id': am.id,
                    'content_id': am.content_item.id,
                    'title': am.content_item.title_ar,
                    'status': am.r2_upload_status or 'pending',
                    'progress': am.r2_upload_progress or 0,
                    'created_at': am.content_item.created_at.isoformat(),
                    'type': 'audio'
                }
                for am in audio_queryset[:100]  # Limit to 100 items
            ]
        
        # PDF content R2 status
        if content_type in ['all', 'pdf']:
            pdf_queryset = PdfMeta.objects.select_related('content_item').only(
                'id', 'r2_upload_status', 'r2_upload_progress',
                'content_item__title_ar', 'content_item__created_at',
                'content_item__id'
            )
            if status_filter == 'all':
                # Show only failed and pending items by default
                pdf_queryset = pdf_queryset.filter(
                    Q(r2_upload_status='failed') | Q(r2_upload_status='pending') | 
                    Q(r2_upload_status='') | Q(r2_upload_status__isnull=True)
                )
            else:
                pdf_queryset = pdf_queryset.filter(r2_upload_status=status_filter)
            
            status_data['pdfs'] = [
                {
                    'id': pm.id,
                    'content_id': pm.content_item.id,
                    'title': pm.content_item.title_ar,
                    'status': pm.r2_upload_status or 'pending',
                    'progress': pm.r2_upload_progress or 0,
                    'created_at': pm.content_item.created_at.isoformat(),
                    'type': 'pdf'
                }
                for pm in pdf_queryset[:100]  # Limit to 100 items
            ]
        
        # Get summary statistics
        status_summary = get_r2_sync_status_data()
        
        context = {
            'status_data': status_data,
            'status_summary': status_summary,
            'current_filter': {
                'status': status_filter,
                'type': content_type
            }
        }
        
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse(context)
        
        return render(request, 'admin/r2_status_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"R2 status dashboard error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required 
@require_POST
def retry_r2_upload(request, content_type, meta_id):
    """
    Retry R2 upload for a specific content item.
    Args:
        content_type: 'video', 'audio', or 'pdf'
        meta_id: ID of the meta object (VideoMeta, AudioMeta, or PdfMeta)
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        from core.tasks.media_processing import upload_video_to_r2, upload_audio_to_r2, upload_pdf_to_r2
        
        # Validate content type
        if content_type not in ['video', 'audio', 'pdf']:
            return JsonResponse({'error': 'Invalid content type'}, status=400)
        
        # Get the meta object and trigger appropriate R2 upload task
        task_id = None
        
        if content_type == 'video':
            from apps.media_manager.models import VideoMeta
            video_meta = get_object_or_404(VideoMeta, id=meta_id)
            video_meta.r2_upload_status = 'pending'  # Reset status
            video_meta.r2_upload_progress = 0
            video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_video_to_r2.delay(str(meta_id))
            task_id = task_result.id
            
        elif content_type == 'audio':
            from apps.media_manager.models import AudioMeta
            audio_meta = get_object_or_404(AudioMeta, id=meta_id)
            audio_meta.r2_upload_status = 'pending'  # Reset status
            audio_meta.r2_upload_progress = 0
            audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_audio_to_r2.delay(str(meta_id))
            task_id = task_result.id
            
        elif content_type == 'pdf':
            from apps.media_manager.models import PdfMeta
            pdf_meta = get_object_or_404(PdfMeta, id=meta_id)
            pdf_meta.r2_upload_status = 'pending'  # Reset status
            pdf_meta.r2_upload_progress = 0
            pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_pdf_to_r2.delay(str(meta_id))
            task_id = task_result.id
        
        logger.info(f"Triggered R2 upload retry for {content_type} {meta_id} (task: {task_id})")
        
        return JsonResponse({
            'success': True,
            'message': f'R2 upload retry triggered for {content_type}',
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"R2 upload retry error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST  
def bulk_retry_r2_uploads(request):
    """
    Bulk retry R2 uploads for multiple content items.
    Expects JSON payload with list of items to retry.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        import json
        from core.tasks.media_processing import upload_video_to_r2, upload_audio_to_r2, upload_pdf_to_r2
        
        # Parse request data
        data = json.loads(request.body)
        items = data.get('items', [])
        
        if not items:
            return JsonResponse({'error': 'No items specified'}, status=400)
        
        results = {
            'success_count': 0,
            'error_count': 0,
            'errors': [],
            'task_ids': []
        }
        
        for item in items:
            content_type = item.get('type')
            meta_id = item.get('id')
            
            try:
                if content_type == 'video':
                    from apps.media_manager.models import VideoMeta
                    video_meta = VideoMeta.objects.get(id=meta_id)
                    video_meta.r2_upload_status = 'pending'
                    video_meta.r2_upload_progress = 0
                    video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_video_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    
                elif content_type == 'audio':
                    from apps.media_manager.models import AudioMeta
                    audio_meta = AudioMeta.objects.get(id=meta_id)
                    audio_meta.r2_upload_status = 'pending'
                    audio_meta.r2_upload_progress = 0
                    audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_audio_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    
                elif content_type == 'pdf':
                    from apps.media_manager.models import PdfMeta
                    pdf_meta = PdfMeta.objects.get(id=meta_id)
                    pdf_meta.r2_upload_status = 'pending'
                    pdf_meta.r2_upload_progress = 0
                    pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_pdf_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    
                else:
                    results['errors'].append(f"Invalid content type for item {meta_id}: {content_type}")
                    results['error_count'] += 1
                    continue
                
                results['success_count'] += 1
                
            except Exception as e:
                error_msg = f"Error retrying {content_type} {meta_id}: {str(e)}"
                results['errors'].append(error_msg)
                results['error_count'] += 1
                logger.error(error_msg)
        
        logger.info(f"Bulk R2 retry: {results['success_count']} successful, {results['error_count']} errors")
        
        return JsonResponse({
            'success': True,
            'message': f'Triggered {results["success_count"]} R2 upload retries',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Bulk R2 retry error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_r2_sync_status(request):
    """
    Get detailed R2 sync status statistics for monitoring dashboard.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        status_data = get_r2_sync_status_data()
        return JsonResponse(status_data)
        
    except Exception as e:
        logger.error(f"R2 sync status error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def get_r2_sync_status_data():
    """Helper function to get R2 sync status data"""
    from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta
    from django.db.models import Count
    
    # Video R2 status counts
    video_status = VideoMeta.objects.values('r2_upload_status').annotate(count=Count('id'))
    video_counts = {status['r2_upload_status']: status['count'] for status in video_status}
    
    # Audio R2 status counts  
    audio_status = AudioMeta.objects.values('r2_upload_status').annotate(count=Count('id'))
    audio_counts = {status['r2_upload_status']: status['count'] for status in audio_status}
    
    # PDF R2 status counts
    pdf_status = PdfMeta.objects.values('r2_upload_status').annotate(count=Count('id'))
    pdf_counts = {status['r2_upload_status']: status['count'] for status in pdf_status}
    
    # Calculate totals
    total_pending = (video_counts.get('pending', 0) + audio_counts.get('pending', 0) + pdf_counts.get('pending', 0))
    total_uploading = (video_counts.get('uploading', 0) + audio_counts.get('uploading', 0) + pdf_counts.get('uploading', 0))
    total_completed = (video_counts.get('completed', 0) + audio_counts.get('completed', 0) + pdf_counts.get('completed', 0))
    total_failed = (video_counts.get('failed', 0) + audio_counts.get('failed', 0) + pdf_counts.get('failed', 0))
    total_items = total_pending + total_uploading + total_completed + total_failed
    
    return {
        'summary': {
            'total_items': total_items,
            'pending': total_pending,
            'uploading': total_uploading, 
            'completed': total_completed,
            'failed': total_failed,
            'completion_rate': round((total_completed / total_items * 100) if total_items > 0 else 0, 1)
        },
        'by_type': {
            'video': video_counts,
            'audio': audio_counts,
            'pdf': pdf_counts
        }
    }


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
                'structured_data': content.structured_data if content.structured_data else {},
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
            structured_data = data.get('structured_data', {})
            if structured_data:
                if isinstance(structured_data, str):
                    try:
                        # Validate it's valid JSON and store as dict
                        content.structured_data = json.loads(structured_data)
                    except json.JSONDecodeError:
                        return JsonResponse({'success': False, 'error': 'Invalid JSON in structured data'})
                elif isinstance(structured_data, dict):
                    content.structured_data = structured_data
                else:
                    return JsonResponse({'success': False, 'error': 'Invalid format for structured data'})
            else:
                content.structured_data = {}
            
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


@login_required
def get_search_sensitivity(request):
    """Get current search sensitivity settings"""
    try:
        search_service = get_search_settings_service()
        settings = search_service.get_all_settings()
        
        # Get all available modes with their descriptions and thresholds
        modes = []
        for mode_key, mode_label in [
            ('exact', 'Exact Match'),
            ('strict', 'Strict'),
            ('normal', 'Normal'),
            ('relaxed', 'Relaxed'),
            ('custom', 'Custom'),
        ]:
            modes.append({
                'key': mode_key,
                'label': mode_label,
                'threshold': search_service.get_threshold_for_mode(mode_key),
                'description': search_service.get_mode_description(mode_key),
                'is_active': settings['mode'] == mode_key
            })
        
        return JsonResponse({
            'success': True,
            'current_settings': settings,
            'available_modes': modes
        })
        
    except Exception as e:
        logger.error(f"Error getting search sensitivity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def update_search_sensitivity(request):
    """Update search sensitivity settings"""
    try:
        data = json.loads(request.body)
        mode = data.get('mode')
        custom_threshold = data.get('custom_threshold')
        
        if not mode:
            return JsonResponse({
                'success': False,
                'error': 'Mode is required'
            }, status=400)
        
        # Update settings with audit logging
        search_service = get_search_settings_service()
        success, message, new_settings = search_service.update_settings(
            mode=mode,
            custom_threshold=custom_threshold,
            user=request.user
        )
        
        if success:
            return JsonResponse({
                'success': True,
                'message': message,
                'settings': new_settings
            })
        else:
            return JsonResponse({
                'success': False,
                'error': message
            }, status=400)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error updating search sensitivity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def test_search_sensitivity(request):
    """Test search with a specific sensitivity setting using UnifiedSearchService"""
    try:
        data = json.loads(request.body)
        search_query = data.get('query', '').strip()
        test_mode = data.get('mode', 'normal')
        custom_threshold = data.get('custom_threshold')
        
        if not search_query:
            return JsonResponse({
                'success': False,
                'error': 'Search query is required'
            }, status=400)
        
        # Get threshold for the test mode
        search_service = get_search_settings_service()
        if test_mode == 'custom' and custom_threshold is not None:
            try:
                threshold = float(custom_threshold)
                if not 0.0 <= threshold <= 1.0:
                    return JsonResponse({
                        'success': False,
                        'error': 'Custom threshold must be between 0.0 and 1.0'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid custom threshold value'
                }, status=400)
        else:
            threshold = search_service.get_threshold_for_mode(test_mode)
        
        # Use UnifiedSearchService for consistent search behavior
        from apps.media_manager.services.unified_search_service import get_unified_search_service
        
        unified_search = get_unified_search_service()
        results_data = unified_search.get_search_preview(
            query=search_query,
            threshold=threshold,
            content_type=None,  # Search all types
            limit=10
        )
        
        return JsonResponse({
            'success': True,
            'query': search_query,
            'mode': test_mode,
            'threshold': threshold,
            'total_results': len(results_data),
            'results': results_data
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error testing search sensitivity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# Google Re-indexing API Endpoints
# ============================================================================

@login_required
@require_POST
def initiate_google_reindexing(request):
    """
    Initiate Google Search Console re-indexing operation.
    
    POST Body:
        content_type: 'all', 'video', 'audio', or 'pdf' (optional, default: 'all')
        include_sitemap: boolean (optional, default: true)
    
    Returns:
        JSON with task_id, estimated_duration, and total_urls
    """
    # Check staff permission
    if not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. Staff access required.'
        }, status=403)
    
    try:
        from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
        from apps.frontend_api.tasks import reindex_website_google
        
        # Parse request body
        data = json.loads(request.body) if request.body else {}
        content_type = data.get('content_type', 'all')
        include_sitemap = data.get('include_sitemap', True)
        
        # Validate content_type
        valid_types = ['all', 'video', 'audio', 'pdf']
        if content_type not in valid_types:
            return JsonResponse({
                'success': False,
                'error': f'Invalid content_type. Must be one of: {", ".join(valid_types)}'
            }, status=400)
        
        # Initialize service
        service = GoogleReindexingService()
        
        # Create task
        try:
            task_id = service.initiate_reindexing(
                user=request.user,
                content_type=content_type,
                include_sitemap=include_sitemap
            )
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        # Get URL count for estimation
        urls = service.get_active_urls(content_type)
        estimated_duration = service.estimate_duration(len(urls))
        
        # Start Celery task asynchronously
        reindex_website_google.delay(task_id, content_type, include_sitemap)
        
        logger.info(
            f"User {request.user.username} initiated re-indexing task {task_id} "
            f"for {len(urls)} URLs (content_type={content_type})"
        )
        
        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'total_urls': len(urls),
            'estimated_duration': estimated_duration,
            'message': 'Re-indexing task initiated successfully'
        })
        
    except Exception as e:
        logger.exception(f"Error initiating re-indexing: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def reindex_status(request, task_id):
    """
    Get real-time status of a re-indexing task.
    
    Returns:
        JSON with task status, progress, and statistics
    """
    # Check staff permission
    if not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. Staff access required.'
        }, status=403)
    
    try:
        from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
        from apps.frontend_api.models import GoogleReindexingTask
        
        service = GoogleReindexingService()
        status_data = service.get_task_status(str(task_id))
        
        if 'error' in status_data:
            return JsonResponse({
                'success': False,
                'error': status_data['error']
            }, status=404)
        
        # Add error details if available
        try:
            task = GoogleReindexingTask.objects.get(id=task_id)
            if task.error_log and task.error_log != '[]':
                errors = json.loads(task.error_log)
                status_data['errors'] = errors[-10:]  # Last 10 errors
        except:
            pass
        
        return JsonResponse({
            'success': True,
            **status_data
        })
        
    except Exception as e:
        logger.exception(f"Error getting task status: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def cancel_reindex(request, task_id):
    """
    Cancel a running re-indexing task.
    
    Returns:
        JSON with cancellation status and partial results
    """
    # Check staff permission
    if not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. Staff access required.'
        }, status=403)
    
    try:
        from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
        
        service = GoogleReindexingService()
        cancelled = service.cancel_task(str(task_id))
        
        if not cancelled:
            return JsonResponse({
                'success': False,
                'error': 'Task cannot be cancelled (already completed or not found)'
            }, status=400)
        
        # Get final status
        status_data = service.get_task_status(str(task_id))
        
        logger.info(f"User {request.user.username} cancelled re-indexing task {task_id}")
        
        return JsonResponse({
            'success': True,
            'cancelled': True,
            'message': 'Re-indexing task cancelled successfully',
            'partial_results': {
                'submitted': status_data.get('submitted', 0),
                'successful': status_data.get('successful', 0),
                'failed': status_data.get('failed', 0),
            }
        })
        
    except Exception as e:
        logger.exception(f"Error cancelling task: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def reindex_history(request):
    """
    Get history of past re-indexing operations.
    
    Query Parameters:
        limit: Maximum number of tasks to return (default: 10, max: 50)
    
    Returns:
        JSON with list of past re-indexing tasks
    """
    # Check staff permission
    if not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. Staff access required.'
        }, status=403)
    
    try:
        from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
        
        # Get limit from query params
        limit = min(int(request.GET.get('limit', 10)), 50)
        
        service = GoogleReindexingService()
        tasks = service.get_reindexing_history(limit=limit)
        
        # Serialize tasks
        tasks_data = []
        for task in tasks:
            tasks_data.append({
                'task_id': str(task.id),
                'status': task.status,
                'content_type': task.content_type,
                'total_urls': task.total_urls,
                'successful_urls': task.successful_urls,
                'failed_urls': task.failed_urls,
                'success_rate': task.get_success_rate(),
                'initiated_by': task.initiated_by.username if task.initiated_by else None,
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                'created_at': task.created_at.isoformat(),
            })
        
        return JsonResponse({
            'success': True,
            'tasks': tasks_data,
            'count': len(tasks_data)
        })
        
    except Exception as e:
        logger.exception(f"Error getting re-indexing history: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def seo_reindex_page(request):
    """
    Render the Google re-indexing control panel page.
    """
    # Check staff permission
    if not request.user.is_staff:
        messages.error(request, _('Permission denied. Staff access required.'))
        return redirect('frontend_api:admin_dashboard')
    
    return render(request, 'admin/seo_reindex.html', {
        'current_language': get_language(),
    })


# ============================================================================
# API Upload Queue Management Views
# ============================================================================

@login_required
def api_queue_list(request):
    """
    Display and manage API upload queue items.
    Supports filtering by status, content type, and pagination.
    """
    from apps.media_manager.models import APIUploadQueue
    from django.core.paginator import Paginator
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    content_type_filter = request.GET.get('content_type', '')
    page_number = request.GET.get('page', 1)
    
    # Build queryset with filters
    queryset = APIUploadQueue.objects.select_related('content_item').order_by('-priority', '-created_at')
    
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    if content_type_filter:
        queryset = queryset.filter(content_type=content_type_filter)
    
    # Get statistics
    stats = {
        'total': APIUploadQueue.objects.count(),
        'pending': APIUploadQueue.objects.filter(status='pending').count(),
        'queued': APIUploadQueue.objects.filter(status='queued').count(),
        'processing': APIUploadQueue.objects.filter(status='processing').count(),
        'completed': APIUploadQueue.objects.filter(status='completed').count(),
        'failed': APIUploadQueue.objects.filter(status='failed').count(),
        'rate_limited': APIUploadQueue.objects.filter(status='rate_limited').count(),
        'cancelled': APIUploadQueue.objects.filter(status='cancelled').count(),
    }
    
    # Get items by content type
    type_stats = {
        'video': APIUploadQueue.objects.filter(content_type='video', status__in=['pending', 'queued', 'processing']).count(),
        'audio': APIUploadQueue.objects.filter(content_type='audio', status__in=['pending', 'queued', 'processing']).count(),
        'pdf': APIUploadQueue.objects.filter(content_type='pdf', status__in=['pending', 'queued', 'processing']).count(),
    }
    
    # Paginate results
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number)
    
    # Calculate queue positions for items
    for item in page_obj:
        item.calculated_position = item.get_queue_position()
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'type_stats': type_stats,
        'status_filter': status_filter,
        'content_type_filter': content_type_filter,
        'status_choices': [
            ('', 'All'),
            ('pending', 'Pending'),
            ('queued', 'Queued'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('rate_limited', 'Rate Limited'),
            ('cancelled', 'Cancelled'),
        ],
        'content_type_choices': [
            ('', 'All Types'),
            ('video', 'Video'),
            ('audio', 'Audio'),
            ('pdf', 'PDF'),
        ],
    }
    
    return render(request, 'admin/api_queue_list.html', context)


@login_required
def api_queue_detail(request, queue_id):
    """Display detailed information about a queue item."""
    from apps.media_manager.models import APIUploadQueue
    
    queue_item = get_object_or_404(
        APIUploadQueue.objects.select_related('content_item'), 
        id=queue_id
    )
    
    context = {
        'queue_item': queue_item,
        'queue_position': queue_item.get_queue_position(),
    }
    
    return render(request, 'admin/api_queue_detail.html', context)


@login_required
@require_POST
def api_queue_promote(request, queue_id):
    """Promote a queue item to process immediately."""
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    from apps.media_manager.models import APIUploadQueue
    
    try:
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        
        # Promote the item
        APIUploadQueueService.promote_item(str(queue_id))
        
        messages.success(
            request, 
            f'Queue item "{queue_item.file_name}" has been promoted and will be processed immediately.'
        )
        
        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Item promoted successfully'
            })
        
        # Redirect for regular requests
        return redirect('frontend_api:api_queue_list')
        
    except Exception as e:
        logger.error(f"Error promoting queue item {queue_id}: {e}", exc_info=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        messages.error(request, f'Error promoting item: {str(e)}')
        return redirect('frontend_api:api_queue_list')


@login_required
@require_POST
def api_queue_cancel(request, queue_id):
    """Cancel a queue item."""
    from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
    from apps.media_manager.models import APIUploadQueue
    
    try:
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        
        # Cancel the item
        APIUploadQueueService.cancel_item(str(queue_id))
        
        messages.success(
            request, 
            f'Queue item "{queue_item.file_name}" has been cancelled.'
        )
        
        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Item cancelled successfully'
            })
        
        # Redirect for regular requests
        return redirect('frontend_api:api_queue_list')
        
    except Exception as e:
        logger.error(f"Error cancelling queue item {queue_id}: {e}", exc_info=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        messages.error(request, f'Error cancelling item: {str(e)}')
        return redirect('frontend_api:api_queue_list')


@login_required
def document_upload(request, content_id):
    """
    Upload supplementary document to existing ContentItem.
    AJAX endpoint for document upload.
    
    POST /dashboard/content/<uuid>/document/upload/
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Method not allowed'
        }, status=405)
    
    try:
        from apps.media_manager.models import ContentItem
        from apps.media_manager.services.upload_service import MediaUploadService
        
        # Get content item
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        # Get document file
        document_file = request.FILES.get('document')
        if not document_file:
            return JsonResponse({
                'success': False,
                'error': 'No document file provided'
            }, status=400)
        
        # Validate file extension
        import os
        file_ext = os.path.splitext(document_file.name)[1].lower()
        if file_ext not in ['.doc', '.docx']:
            return JsonResponse({
                'success': False,
                'error': 'Only .doc and .docx files are supported'
            }, status=400)
        
        # Attach document
        upload_service = MediaUploadService()
        result = upload_service.attach_supplementary_document(str(content_id), document_file)
        
        if result.get('success'):
            return JsonResponse({
                'success': True,
                'message': result.get('message'),
                'document_name': result.get('document_name'),
                'document_size': result.get('document_size'),
                'status': result.get('status')
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error')
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error uploading document to {content_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def document_download(request, content_id):
    """
    Download supplementary document.
    
    GET /dashboard/content/<uuid>/document/download/
    """
    try:
        from django.http import FileResponse
        from apps.media_manager.models import ContentItem
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            messages.error(request, 'No document attached to this content')
            return redirect('frontend_api:content_detail', content_id=content_id)
        
        # Get file path and create response - FileResponse handles closing
        file_path = content_item.supplementary_document.path
        response = FileResponse(
            open(file_path, 'rb'),
            as_attachment=True,
            filename=content_item.supplementary_document_name
        )
        
        # Set additional headers
        response['Content-Type'] = content_item.supplementary_document_type or 'application/octet-stream'
        response['Content-Length'] = content_item.supplementary_document_size
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading document from {content_id}: {str(e)}", exc_info=True)
        messages.error(request, 'Error downloading document')
        return redirect('frontend_api:content_detail', content_id=content_id)


@login_required
def document_delete(request, content_id):
    """
    Delete supplementary document.
    AJAX endpoint for document deletion.
    
    DELETE /dashboard/content/<uuid>/document/delete/
    """
    if request.method not in ['POST', 'DELETE']:
        return JsonResponse({
            'success': False,
            'error': 'Method not allowed'
        }, status=405)
    
    try:
        from apps.media_manager.models import ContentItem
        from apps.media_manager.services.upload_service import MediaUploadService
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            return JsonResponse({
                'success': False,
                'error': 'No document attached to this content'
            }, status=404)
        
        # Delete document
        upload_service = MediaUploadService()
        result = upload_service.delete_supplementary_document(str(content_id))
        
        if result.get('success'):
            return JsonResponse({
                'success': True,
                'message': result.get('message')
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error')
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error deleting document from {content_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
