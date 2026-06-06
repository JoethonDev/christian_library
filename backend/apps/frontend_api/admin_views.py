"""
Optimized Admin Views for Content Management
Refactored to use AdminService layer and eliminate N+1 queries.
All administrative operations now use minimal database queries.
"""
import json
import logging
import os
import re
import tempfile
import mimetypes
import zipfile
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST
import io
from django.http.multipartparser import MultiPartParser

from apps.frontend_api.admin_services import AdminService
from apps.media_manager.models import (
    APIUploadQueue, ContentItem, ContentLifecycleAuditLog, ContentViewEvent,
    DailyContentViewSummary, GeminiModelSetting, ProcessingJob, Tag, VideoMeta, AudioMeta, PdfMeta,
)
from apps.media_manager.models import ChunkedUploadSession
from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService
from apps.media_manager.services.content_service import ContentService
from apps.media_manager.services.delete_service import MediaProcessingService
from apps.media_manager.services.lifecycle_audit_service import LifecycleAuditService
from apps.media_manager.services.search_settings_service import get_search_settings_service
from apps.media_manager.services.unified_search_service import get_unified_search_service
from apps.media_manager.services.upload_service import MediaUploadService
from core.tasks.media_finalization import generate_seo_metadata_task
from core.services.gemini_manager import get_gemini_manager
from core.services.gemini_metadata_service import get_gemini_metadata_service
from core.services.gemini_seo_service import get_gemini_seo_service
from core.services.r2_storage_service import get_r2_storage_service
from core.storage_backends import R2Service
from core.tasks.media_processing import (
    upload_video_to_r2,
    upload_audio_to_r2,
    upload_pdf_to_r2,
)
from apps.frontend_api.utils.jobs_dashboard import (
    dispatch_content_item_for_stage,
    dispatch_processing_task,
    ensure_staff,
    get_all_jobs,
    get_jobs_counts,
    parse_request_payload,
)
from config import celery_app

logger = logging.getLogger(__name__)

staff_member_required = user_passes_test(
    lambda u: u.is_active and u.is_staff,
    login_url='frontend_api:admin_login',
)

# Lazy service initializers (avoid eager DB access at import time)
_admin_service_instance = None
def get_admin_service():
    global _admin_service_instance
    if _admin_service_instance is None:
        _admin_service_instance = AdminService()
    return _admin_service_instance

content_service = ContentService()


@staff_member_required
def admin_dashboard(request):
    """Main admin dashboard - Optimized to 4 queries total"""
    # Get all dashboard data with optimized service
    dashboard_data = get_admin_service().get_dashboard_data()
    
    return render(request, 'admin/dashboard.html', dashboard_data)


@staff_member_required
def content_list(request):
    """List all content - Optimized to 1-2 queries total"""
    # Get filters from request
    content_type = request.GET.get('type', '')
    search_query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    ordering = request.GET.get('sort', '-created_at')
    per_page = int(request.GET.get('limit', 20))
    
    # Get content list using optimized service
    content_data = get_admin_service().get_content_list(
        content_type=content_type,
        search_query=search_query,
        page=page,
        per_page=per_page,
        ordering=ordering
    )
    
    context = {
        'content_type': content_type,
        'search_query': search_query,
        'content_data': content_data,
        'current_language': get_language(),
        'ordering': ordering,
        'per_page': per_page,
    }
    
    # HTMX partial support
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/content_list.html', context)
    
    return render(request, 'admin/content_list.html', context)


@staff_member_required
def content_detail(request, content_id):
    """Content detail page - Single optimized query"""
    try:
        # Get content with all relations in single query
        content = get_admin_service().get_content_detail(str(content_id))
        
        # Handle POST request for status/metadata updates
        if request.method == 'POST':
            # Handle is_active toggle
            if 'toggle_active' in request.POST:
                success, message = get_admin_service().toggle_content_status(str(content_id))
                if success:
                    refreshed_content = get_admin_service().get_content_detail(str(content_id))
                    LifecycleAuditService.log_event(
                        content_item=refreshed_content,
                        action_type='content_status_toggled',
                        actor=request.user,
                        source='admin:content_detail',
                        previous_state='active' if not refreshed_content.is_active else 'inactive',
                        new_state='active' if refreshed_content.is_active else 'inactive',
                        message='Content active status toggled from admin content detail',
                        payload={'content_id': str(refreshed_content.id), 'is_active': refreshed_content.is_active},
                    )
                    messages.success(request, message)
                else:
                    messages.error(request, message)
            else:
                previous_snapshot = {
                    'title_ar': content.title_ar,
                    'title_en': content.title_en,
                    'description_ar': content.description_ar,
                    'description_en': content.description_en,
                    'seo_title_ar': content.seo_title_ar,
                    'seo_title_en': content.seo_title_en,
                    'seo_keywords_ar': content.seo_keywords_ar,
                    'seo_keywords_en': content.seo_keywords_en,
                    'seo_meta_description_ar': content.seo_meta_description_ar,
                    'seo_meta_description_en': content.seo_meta_description_en,
                    'structured_data': content.structured_data,
                    'notes': content.notes,
                    'transcript': content.transcript,
                }
                # Handle general metadata updates
                title_ar = request.POST.get('title_ar')
                title_en = request.POST.get('title_en')
                description_ar = request.POST.get('description_ar')
                description_en = request.POST.get('description_en')
                notes = request.POST.get('notes', '')
                transcript = request.POST.get('transcript', '')
                seo_title_ar = request.POST.get('seo_title_ar', '')
                seo_title_en = request.POST.get('seo_title_en', '')
                seo_meta_description_ar = request.POST.get('seo_meta_description_ar', '')
                seo_meta_description_en = request.POST.get('seo_meta_description_en', '')
                seo_keywords_ar = request.POST.get('seo_keywords_ar', '')
                seo_keywords_en = request.POST.get('seo_keywords_en', '')
                structured_data = request.POST.get('structured_data', '')
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
                content.seo_meta_description_ar = seo_meta_description_ar
                content.seo_meta_description_en = seo_meta_description_en
                content.seo_keywords_ar = seo_keywords_ar
                content.seo_keywords_en = seo_keywords_en
                content.structured_data = structured_data if structured_data else None
                
                update_fields = [
                    'title_ar', 'title_en', 'description_ar', 'description_en',
                    'notes', 'transcript', 'seo_title_ar', 'seo_title_en',
                    'seo_meta_description_ar', 'seo_meta_description_en',
                    'seo_keywords_ar', 'seo_keywords_en', 'structured_data', 'updated_at'
                ]
                
                if thumbnail_file:
                    # Clean up old files before saving new one
                    try:
                        # 1. Delete physical local file if it exists
                        if content.thumbnail and hasattr(content.thumbnail, 'path'):
                            if os.path.exists(content.thumbnail.path):
                                os.remove(content.thumbnail.path)
                                logger.info(f"Deleted old local thumbnail: {content.thumbnail.path}")
                        
                        # 2. Delete from R2 if it exists
                        if content.r2_thumbnail_url:
                            r2 = R2Service()
                            if r2.use_r2:
                                # Key is the name of the file in the ImageField
                                r2_key = content.thumbnail.name if content.thumbnail else None
                                if r2_key:
                                    r2._r2_service.delete_file(r2_key)
                                    logger.info(f"Deleted old thumbnail from R2: {r2_key}")
                    except Exception as e:
                        logger.warning(f"Error while cleaning up old thumbnail: {e}")

                    # 3. Update with new thumbnail
                    content.thumbnail = thumbnail_file
                    content.r2_thumbnail_url = '' # Reset R2 URL until new upload completes
                    update_fields.extend(['thumbnail', 'r2_thumbnail_url'])
                
                content.save(update_fields=update_fields)
                
                # 4. Handle R2 upload for the new thumbnail if enabled
                if thumbnail_file and getattr(settings, 'R2_ENABLED', False):
                    try:
                        r2 = R2Service()
                        if r2.use_r2:
                            r2.upload_thumbnail(content)
                            logger.info(f"Uploaded new thumbnail to R2 for content {content_id}")
                    except Exception as e:
                        logger.error(f"Failed to upload new thumbnail to R2: {e}")
                
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

                LifecycleAuditService.log_event(
                    content_item=content,
                    action_type='content_manual_edit',
                    actor=request.user,
                    source='admin:content_detail',
                    previous_state='metadata_saved',
                    new_state='metadata_saved',
                    message='Content metadata manually edited from admin content detail',
                    payload={
                        'content_id': str(content.id),
                        'fields_before': previous_snapshot,
                        'fields_after': {
                            'title_ar': content.title_ar,
                            'title_en': content.title_en,
                            'description_ar': content.description_ar,
                            'description_en': content.description_en,
                            'seo_title_ar': content.seo_title_ar,
                            'seo_title_en': content.seo_title_en,
                            'seo_keywords_ar': content.seo_keywords_ar,
                            'seo_keywords_en': content.seo_keywords_en,
                            'seo_meta_description_ar': content.seo_meta_description_ar,
                            'seo_meta_description_en': content.seo_meta_description_en,
                            'structured_data': content.structured_data,
                            'notes': content.notes,
                            'transcript': content.transcript,
                        },
                        'tags_input': tags_input,
                        'thumbnail_updated': bool(thumbnail_file),
                    },
                )
                
                # Compute SEO processing status from field presence
                has_ar = bool(content.seo_title_ar or content.seo_meta_description_ar or content.seo_keywords_ar)
                has_en = bool(content.seo_title_en or content.seo_meta_description_en or content.seo_keywords_en)
                if has_ar and has_en:
                    content.seo_processing_status = 'completed'
                elif has_ar or has_en:
                    content.seo_processing_status = 'processing' if content.seo_processing_status != 'completed' else 'completed'
                else:
                    content.seo_processing_status = 'pending'
                update_fields.append('seo_processing_status')
                
                messages.success(request, _("Sacred metadata updated successfully"))
            
            # Re-fetch content to reflect changes
            content = get_admin_service().get_content_detail(str(content_id))

        # Process for current language
        processed_content = get_admin_service().language_processor.process_content_item(
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


@staff_member_required
def content_delete_confirm(request, content_id):
    """Handle content deletion - Optimized with single query check"""
    try:
        # Get content with all relations in single query
        content = get_admin_service().get_content_detail(str(content_id))
        
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
        processed_content = get_admin_service().language_processor.process_content_item(
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
        messages.error(request, _("Error processing delete request: %(error)s") % {"error": str(e)})
        return redirect('frontend_api:admin_content_detail', content_id=content_id)


@staff_member_required
def delete_local_confirm(request, content_id):
    """Handle local file deletion only, preserving R2 and DB record."""
    try:
        content = get_admin_service().get_content_detail(str(content_id))
        
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
                    return redirect('frontend_api:media_management', media_type='video')
                elif content.content_type == 'audio':
                    return redirect('frontend_api:media_management', media_type='audio')
                elif content.content_type == 'pdf':
                    return redirect('frontend_api:media_management', media_type='pdf')
                return redirect('frontend_api:admin_content_list')
            else:
                messages.error(request, message)
                return redirect('frontend_api:admin_content_detail', content_id=content_id)

        # GET request - Show confirmation page
        processed_content = get_admin_service().language_processor.process_content_item(
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
        messages.error(request, _("Error processing request: %(error)s") % {"error": str(e)})
        return redirect('frontend_api:admin_content_list')


@staff_member_required
def upload_content(request):
    """Upload content page"""
    return render(request, 'admin/upload_content.html', {
        'current_language': get_language(),
    })


# Legacy monolithic single-upload handler removed. Use chunked upload endpoints:
# - POST to {% url 'frontend_api:bulk_upload_init' %} to create session
# - PATCH to {% url 'frontend_api:bulk_upload_chunk' %} to upload chunks


@staff_member_required
def bulk_upload_page(request):
    """Render the bulk upload page."""
    return render(request, 'admin/bulk_upload.html', {
        'current_language': get_language(),
    })


@staff_member_required
@csrf_protect
@require_http_methods(["POST"])
def bulk_upload_init(request):
    """
    Initialize a chunked upload session.

    Expected JSON body: { filename: str, total_size: int, title_ar: str, title_en: str, tag_ids: [..] }
    Returns: { success: True, session_id: <uuid>, chunk_url: <url> }
    """
    try:
        try:
            payload = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            return JsonResponse({'success': False, 'error': _('Invalid JSON')}, status=400)

        filename = payload.get('filename')
        total_size = int(payload.get('total_size', 0))

        if not filename or total_size <= 0:
            return JsonResponse({'success': False, 'error': _('filename and total_size are required')}, status=400)

        # Collect canonical metadata fields from payload. Store these on session
        # so the finalization step can create the ContentItem with the provided
        # metadata (title, description, tags, seo, transcript, notes, etc.).
        metadata = {
            'title_ar': payload.get('title_ar', ''),
            'title_en': payload.get('title_en', ''),
            'description_ar': payload.get('description_ar', ''),
            'description_en': payload.get('description_en', ''),
            'tag_ids': payload.get('tag_ids', []) or [],
            'seo_title_en': payload.get('seo_title_en', ''),
            'seo_title_ar': payload.get('seo_title_ar', ''),
            'seo_description_en': payload.get('seo_meta_description_en') or payload.get('seo_description_en', ''),
            'seo_description_ar': payload.get('seo_meta_description_ar') or payload.get('seo_description_ar', ''),
            'seo_keywords_en': payload.get('seo_keywords_en', ''),
            'seo_keywords_ar': payload.get('seo_keywords_ar', ''),
            'transcript': payload.get('transcript', ''),
            'notes': payload.get('notes', ''),
            'seo_structured_data': payload.get('structured_data') or payload.get('seo_structured_data', ''),
        }

        session = ChunkedUploadSession.objects.create(
            filename=filename,
            total_size=total_size,
            current_offset=0,
            metadata=metadata
        )

        LifecycleAuditService.log_event(
            content_item=None,
            action_type='upload_initiated',
            actor=request.user,
            source='admin:bulk_upload_init',
            previous_state='',
            new_state='pending',
            message='Chunked upload session created from admin upload page',
            payload={
                'session_id': str(session.id),
                'filename': filename,
                'total_size': total_size,
            },
        )

        # Ensure staging directory is under MEDIA_ROOT so os.replace remains atomic
        staging_dir = os.path.join(settings.MEDIA_ROOT, 'chunked_uploads')
        os.makedirs(staging_dir, exist_ok=True)
        staging_path = os.path.join(staging_dir, f"{session.id}.part")
        session.staging_path = staging_path
        session.save(update_fields=['staging_path'])

        return JsonResponse({
            'success': True,
            'session_id': str(session.id),
            'chunk_url': reverse('frontend_api:bulk_upload_chunk')
        })

    except Exception as e:
        logger.error(f"bulk_upload_init failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
@csrf_protect
@require_http_methods(["PATCH", "POST"])
def bulk_upload_chunk(request):
    """
    Accept a single file chunk (sent as multipart/form-data with field 'chunk').

    Expects: form field 'session_id' and file field 'chunk'.
    Returns: { success: True, offset: int, final: bool, content_id: <uuid> (if final) }
    """
    try:
        # For non-POST methods ensure Django parses POST and FILES
        if request.method != 'POST':
            # Try the regular internal loader first (may not parse multipart for PATCH)
            try:
                request._load_post_and_files()
            except Exception:
                # Fallback: for PATCH multipart requests Django may not populate
                # request.POST/FILES automatically. Try parsing manually with
                # MultiPartParser using the raw body.
                try:
                    content_type = request.META.get('CONTENT_TYPE', '')
                    if content_type.startswith('multipart/'):
                        parser = MultiPartParser(request.META, io.BytesIO(request.body), request.upload_handlers)
                        post, files = parser.parse()
                        # Assign parsed data back to request for downstream code
                        request.POST = post
                        request._files = files
                except Exception as e:
                    logger.debug(f"Manual multipart parse failed: {e}")

        session_id = request.POST.get('session_id') or request.GET.get('session_id')
        if not session_id:
            return JsonResponse({'success': False, 'error': _('session_id is required')}, status=400)

        try:
            session = ChunkedUploadSession.objects.get(id=session_id)
        except ChunkedUploadSession.DoesNotExist:
            return JsonResponse({'success': False, 'error': _('session not found')}, status=404)

        # Expect multipart file field named 'chunk'
        chunk_file = request.FILES.get('chunk')
        if not chunk_file:
            return JsonResponse({'success': False, 'error': _('chunk file required (multipart/form-data)')}, status=400)

        # Append chunk to staging file using UploadedFile.chunks() to avoid high RAM usage
        os.makedirs(os.path.dirname(session.staging_path), exist_ok=True)
        with open(session.staging_path, 'ab') as dest:
            for chunk in chunk_file.chunks():
                dest.write(chunk)

        # Update offset
        current_size = os.path.getsize(session.staging_path)
        session.current_offset = current_size
        session.save(update_fields=['current_offset', 'updated_at'])

        response = {'success': True, 'offset': session.current_offset, 'session_id': str(session.id)}

        # If we've reached or exceeded expected size, finalize and hand off to service
        if session.current_offset >= session.total_size:
            upload_service = MediaUploadService()
            try:
                # This method will atomically move the assembled file into MEDIA_ROOT
                result = upload_service.create_content_item_from_path(
                    session.staging_path,
                    session.filename,
                    session.metadata
                )

                if result.get('success') and result.get('content_item'):
                    content_item = result['content_item']
                    session.is_complete = True
                    session.save(update_fields=['is_complete'])

                    # Provide helpful URLs in the response so the client can attach
                    # supplementary files (thumbnail/document) and navigate.
                    try:
                        content_detail_url = reverse('frontend_api:admin_content_detail', args=[str(content_item.id)])
                    except Exception:
                        content_detail_url = ''
                    try:
                        document_upload_url = reverse('frontend_api:document_upload', args=[str(content_item.id)])
                    except Exception:
                        document_upload_url = ''
                    try:
                        thumbnail_upload_url = reverse('frontend_api:thumbnail_upload', args=[str(content_item.id)])
                    except Exception:
                        thumbnail_upload_url = ''

                    response.update({
                        'final': True,
                        'content_id': str(content_item.id),
                        'message': result.get('message', 'Queued for processing'),
                        'content_detail_url': content_detail_url,
                        'document_upload_url': document_upload_url,
                        'thumbnail_upload_url': thumbnail_upload_url,
                    })
                else:
                    response.update({'final': True, 'error': result.get('error', 'Failed to process assembled file')})

            except Exception as e:
                logger.error(f"Error finalizing chunked upload {session.id}: {e}", exc_info=True)
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        return JsonResponse(response)

    except Exception as e:
        logger.error(f"bulk_upload_chunk failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# Legacy monolithic bulk upload handler removed. Use chunked endpoints instead:
# - POST to {% url 'frontend_api:bulk_upload_init' %} to create per-file sessions
# - PATCH to {% url 'frontend_api:bulk_upload_chunk' %} to stream chunks for each session


@staff_member_required
def bulk_upload_status(request):
    """Return per-item processing status for bulk uploads."""
    content_ids_raw = request.GET.get('ids', '')
    content_ids = [content_id.strip() for content_id in content_ids_raw.split(',') if content_id.strip()][:50]

    if not content_ids:
        return JsonResponse({'success': False, 'error': _('ids is required')}, status=400)

    jobs = ProcessingJob.objects.filter(content_item_id__in=content_ids).only(
        'content_item_id', 'status', 'current_stage', 'failure_reason'
    )
    job_map = {str(job.content_item_id): job for job in jobs}

    statuses = []
    for content_id in content_ids:
        job = job_map.get(content_id)
        statuses.append({
            'content_id': content_id,
            'status': job.status if job else 'pending',
            'stage': job.current_stage if job else 'file_processing',
            'error': job.failure_reason if job else '',
        })

    return JsonResponse({'success': True, 'statuses': statuses})


@staff_member_required
@require_POST
@csrf_protect
def generate_content_metadata(request):
    """Generate content metadata using Gemini AI"""
    try:
        content_id = request.POST.get('content_id')
        if not content_id:
            return JsonResponse({'success': False, 'error': _('Content ID required')})
        
        # Get content item
        content = get_admin_service().get_content_detail(content_id)
        
        # Use Gemini manager to generate metadata
        meta_obj = content.get_meta_object()
        if not meta_obj or not meta_obj.original_file:
            return JsonResponse({'success': False, 'error': _('No media file found for content')})

        LifecycleAuditService.log_event(
            content_item=content,
            action_type='gemini_processing_started',
            actor=request.user,
            source='admin:generate_content_metadata',
            previous_state='pending',
            new_state='processing',
            message='Gemini metadata generation started from admin content API',
            payload={'content_id': str(content.id), 'content_type': content.content_type},
        )

        success, metadata = get_gemini_manager().generate_metadata(
            meta_obj.original_file.path, content.content_type
        )

        if success:
            # Update content with generated metadata
            content.update_seo_from_gemini(metadata)

            LifecycleAuditService.log_event(
                content_item=content,
                action_type='gemini_processing_completed',
                actor=request.user,
                source='admin:generate_content_metadata',
                previous_state='processing',
                new_state='completed',
                message='Gemini metadata generation completed from admin content API',
                payload={'content_id': str(content.id), 'content_type': content.content_type},
            )
            
            return JsonResponse({
                'success': True,
                'message': _('Metadata generated successfully'),
                'metadata': metadata
            })
        else:
            return JsonResponse({
                'success': False,
                'error': metadata.get('error', _('Metadata generation failed')) if isinstance(metadata, dict) else _('Metadata generation failed')
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def _render_media_management(request, media_type):
    """Render a media management page/partial for the requested media type."""
    media_configs = {
        'video': {
            'title': _('Video Manager'),
            'subtitle': _('Manage video sermons, teachings, and spiritual content'),
            'add_label': _('Add Video'),
            'add_icon': 'bi-camera-video',
            'add_button_class': 'btn-danger text-white',
            'search_placeholder': _('Search videos...'),
            'empty_kind_label': _('video'),
            'bulk_generate_label': _('Generate SEO metadata for selected videos?'),
            'single_generate_label': _('Generate SEO metadata for this video?'),
            'delete_confirm_label': _('Delete selected videos?'),
            'delete_success_label': _('Videos deleted successfully'),
            'delete_failure_label': _('Failed to delete videos'),
            'partial': 'admin/partials/video_table.html',
            'context_key': 'videos',
            'extra_filters': {'processing_status': request.GET.get('processing_status', '')},
        },
        'audio': {
            'title': _('Audio Manager'),
            'subtitle': _('Manage audio messages, sermons, and spiritual teachings'),
            'add_label': _('Add Audio'),
            'add_icon': 'bi-mic',
            'add_button_class': 'btn-warning text-white',
            'search_placeholder': _('Search audio...'),
            'empty_kind_label': _('audio file'),
            'bulk_generate_label': _('Generate SEO metadata for selected audio files?'),
            'single_generate_label': _('Generate SEO metadata for this audio file?'),
            'delete_confirm_label': _('Delete selected audio files?'),
            'delete_success_label': _('Audio files deleted successfully'),
            'delete_failure_label': _('Failed to delete audio files'),
            'partial': 'admin/partials/audio_table.html',
            'context_key': 'audios',
            'extra_filters': {},
        },
        'pdf': {
            'title': _('PDF Manager'),
            'subtitle': _('Manage books, documents, and sacred texts'),
            'add_label': _('Add PDF'),
            'add_icon': 'bi-plus-lg',
            'add_button_class': 'btn-primary',
            'search_placeholder': _('Search in titles, descriptions, and content...'),
            'empty_kind_label': _('PDF'),
            'bulk_generate_label': _('Generate SEO metadata for selected PDFs?'),
            'single_generate_label': _('Generate SEO metadata for this PDF?'),
            'delete_confirm_label': _('Delete selected PDFs?'),
            'delete_success_label': _('PDFs deleted successfully'),
            'delete_failure_label': _('Failed to delete PDFs'),
            'partial': 'admin/partials/pdf_table.html',
            'context_key': 'pdfs',
            'extra_filters': {},
        },
    }

    config = media_configs.get(media_type)
    if not config:
        raise Http404(_('Unsupported media type'))

    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('limit', 20))
    ordering = request.GET.get('sort', '-created_at')

    filters = {
        'status': request.GET.get('status', ''),
        'search': request.GET.get('search', '').strip(),
        'missing_data': request.GET.get('missing_data', '')
    }
    filters.update(config['extra_filters'])

    media_data = get_admin_service().get_type_specific_content(
        content_type=media_type,
        page=page,
        per_page=per_page,
        filters=filters,
        ordering=ordering
    )

    context = {
        'content_type': media_type,
        'management_ui': config,
        'partial_template': config['partial'],
        'filters': filters,
        config['context_key']: media_data.get('content_items', []),
        'pagination': media_data.get('pagination'),
        'current_language': get_language(),
        'ordering': ordering,
        'per_page': per_page,
    }

    if request.headers.get('HX-Request') == 'true':
        return render(request, config['partial'], context)

    return render(request, 'admin/media_management_base.html', context)


@staff_member_required
def media_management(request, media_type):
    """Unified media management controller for video, audio, and pdf pages."""
    return _render_media_management(request, media_type)


@staff_member_required
def system_monitor(request):
    """System monitoring dashboard - Optimized queries"""
    from apps.admin_django.views_system import (
        get_database_stats,
        get_media_counts,
        get_redis_stats,
        get_system_stats,
    )

    system_data = get_admin_service().get_system_monitor_data()
    
    context = {
        **system_data,
        'system_stats': get_system_stats(),
        'database_stats': get_database_stats(),
        'redis_stats': get_redis_stats(),
        'media_counts': get_media_counts(),
        'current_language': get_language(),
    }
    
    return render(request, 'admin/system_monitor.html', context)


# ──────────────────────────────────────────────────────────────────
# FILE MANAGER — custom admin dashboard at /dashboard/system/files/
# ──────────────────────────────────────────────────────────────────

@staff_member_required
def file_manager(request):
    """Browse and manage files in media / static / logs directories."""
    from apps.admin_django.views_system import (
        ALLOWED_BASES,
        list_directory,
    )
    base_key = request.GET.get("base", "media")
    rel_path = request.GET.get("path", "")
    if base_key not in ALLOWED_BASES:
        base_key = "media"

    listing = list_directory(base_key, rel_path)
    context = {
        "base_key": base_key,
        "rel_path": rel_path,
        "entries": listing["entries"],
        "crumbs": listing["crumbs"],
        "bases": list(ALLOWED_BASES.keys()),
        "is_root": listing["is_root"],
        "list_error": listing.get("error"),
        "current_language": get_language(),
    }
    return render(request, "admin/file_manager.html", context)


@staff_member_required
@csrf_protect
@require_POST
def file_manager_action(request):
    """AJAX endpoint for file operations (mkdir / delete / rename / move)."""
    from apps.admin_django.views_system import execute_file_action, ALLOWED_BASES

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    action = data.get("action", "")
    base_key = data.get("base", "media")
    rel_path = data.get("path", "")

    if base_key not in ALLOWED_BASES:
        return JsonResponse({"ok": False, "error": "Invalid base"}, status=400)

    result = execute_file_action(
        action,
        base_key,
        rel_path,
        name=data.get("name", ""),
        new_name=data.get("new_name", ""),
        dest_path=data.get("dest_path", ""),
    )
    status = 200 if result.get("ok") else 400
    return JsonResponse(result, status=status)


@staff_member_required
def file_manager_download(request):
    """Download a file directly or zip a folder before downloading it."""
    from apps.admin_django.views_system import ALLOWED_BASES, resolve_safe_path

    base_key = request.GET.get("base", "media")
    rel_path = request.GET.get("path", "")

    if base_key not in ALLOWED_BASES:
        raise Http404("Invalid base")

    target = resolve_safe_path(base_key, rel_path)
    if target is None or not target.exists():
        raise Http404("File not found")

    if target.is_dir():
        if not rel_path.strip():
            raise Http404("Root directory download is not supported")

        archive_name = f"{target.name}.zip"
        buffer = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024, mode="w+b")
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for item in target.rglob("*"):
                if item.is_file():
                    archive.write(item, arcname=item.relative_to(target).as_posix())
        buffer.seek(0)

        response = FileResponse(buffer, as_attachment=True, filename=archive_name)
        response["Content-Type"] = "application/zip"
        return response

    download_name = target.name
    response = FileResponse(target.open("rb"), as_attachment=True, filename=download_name)
    response["Content-Type"] = mimetypes.guess_type(download_name)[0] or "application/octet-stream"
    response["Content-Length"] = str(target.stat().st_size)
    return response


@staff_member_required
def orphaned_files(request):
    """Find files on disk that have no matching DB record."""
    from apps.admin_django.views_system import scan_orphaned_files, delete_orphan

    message = None
    if request.method == "POST":
        rel_path = request.POST.get("rel_path", "")
        res = delete_orphan(rel_path)
        if res.get("ok"):
            messages.success(request, res["message"])
        else:
            messages.error(request, res.get("error", "Delete failed"))
        return redirect("frontend_api:orphaned_files")

    scan = scan_orphaned_files()
    context = {
        "orphans": scan["orphans"],
        "orphan_count": scan["orphan_count"],
        "orphan_size": scan["orphan_size"],
        "total_files": scan["total_files"],
        "elapsed": scan["elapsed"],
        "current_language": get_language(),
    }
    return render(request, "admin/orphaned_files.html", context)


@staff_member_required
def cache_manager(request):
    """View and manage the Redis / Django cache."""
    from apps.admin_django.views_system import get_cache_stats, execute_cache_action

    if request.method == "POST":
        action = request.POST.get("action", "")
        pattern = request.POST.get("pattern", "").strip()
        res = execute_cache_action(action, pattern or None)
        if res.get("ok"):
            messages.success(request, res["message"])
        else:
            messages.error(request, res.get("error", "Action failed"))
        return redirect("frontend_api:cache_manager")

    stats = get_cache_stats()
    context = {
        "cache_stats": stats,
        "current_language": get_language(),
    }
    return render(request, "admin/cache_manager.html", context)


@staff_member_required
def bulk_operations(request):
    """Bulk operations page - Optimized queries"""
    if request.method == 'POST':
        operation = request.POST.get('operation')
        # Handle content_ids[] or content_ids (from textarea)
        content_ids_str = request.POST.get('content_ids[]', '') or request.POST.get('content_ids', '')
        
        # Parse IDs (comma or newline separated)
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
                        content = get_admin_service().get_content_detail(cid)
                        success, _delete_message = processing_service.delete_content(content)
                        if success:
                            success_count += 1
                    except Exception as exc:
                        logger.warning("Bulk delete failed for content %s: %s", cid, exc)
                
                if success_count > 0:
                    messages.success(request, _(f"Successfully deleted {success_count} item(s)"))
                if success_count < len(content_ids):
                    messages.warning(request, _("Failed to delete some item(s). Check if IDs are correct."))
            
            return redirect('frontend_api:bulk_operations')

    # Get bulk operation data
    bulk_data = get_admin_service().get_bulk_operation_data()
    
    context = {
        'bulk_stats': bulk_data,
        'current_language': get_language(),
    }
    
    return render(request, 'admin/bulk_operations.html', context)


@staff_member_required
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
            return JsonResponse({'success': False, 'error': _('Content ID required')})
        
        # Toggle status using optimized service
        success, message = get_admin_service().toggle_content_status(content_id)
        
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
        return JsonResponse({'success': False, 'error': _('Invalid JSON')})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# Bulk operation API endpoints
@staff_member_required
@require_POST
@csrf_protect
def api_bulk_generate_seo(request):
    """Bulk SEO generation API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': _('No content IDs provided')})
        
        # Process each content item
        results = []

        for content_id in content_ids:
            try:
                content = get_admin_service().get_content_detail(content_id)
                meta_obj = content.get_meta_object()
                if not meta_obj or not meta_obj.original_file:
                    results.append({'id': content_id, 'success': False, 'error': 'No media file'})
                    continue
                success, metadata = get_gemini_manager().generate_metadata(
                    meta_obj.original_file.path, content.content_type
                )

                if success:
                    content.update_seo_from_gemini(metadata)
                    results.append({'id': content_id, 'success': True})
                else:
                    results.append({'id': content_id, 'success': False, 'error':
                        metadata.get('error') if isinstance(metadata, dict) else 'Generation failed'})
                    
            except Exception as e:
                results.append({'id': content_id, 'success': False, 'error': str(e)})
        
        success_count = sum(1 for r in results if r['success'])
        
        return JsonResponse({
            'success': True,
            'message': _('SEO metadata generated for %(success)s/%(total)s items') % {
                'success': success_count,
                'total': len(content_ids)
            },
            'results': results
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
@require_POST
@csrf_protect
def api_bulk_toggle_status(request):
    """Bulk status toggle API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        target_status = data.get('status', True)  # True for active, False for inactive
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': _('No content IDs provided')})
        
        # Bulk update using single query
        updated_count = ContentItem.objects.filter(
            id__in=content_ids
        ).update(is_active=target_status)
        
        status_text = _("active") if target_status else _("inactive")
        
        return JsonResponse({
            'success': True,
            'message': _('%(count)s items set to %(status)s') % {'count': updated_count, 'status': status_text},
            'updated_count': updated_count
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
@require_POST
@csrf_protect
def api_bulk_delete(request):
    """Bulk delete API endpoint"""
    try:
        data = json.loads(request.body)
        content_ids = data.get('content_ids', [])
        
        if not content_ids:
            return JsonResponse({'success': False, 'error': _('No content IDs provided')})
        
        # Use processing service for proper deletion
        processing_service = MediaProcessingService()
        results = []
        
        for content_id in content_ids:
            try:
                # Use admin_service to get the object with relations
                content = get_admin_service().get_content_detail(content_id)
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
                    'message': _('Content not found')
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
            'message': _('%(success)s/%(total)s items deleted successfully') % {
                'success': success_count,
                'total': len(content_ids)
            },
            'results': results
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
@require_POST
@csrf_protect
def generate_metadata_from_file(request):
    """Generate metadata from uploaded file (before content creation)"""
    try:
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': _('File required')})
        
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
                return JsonResponse({'success': False, 'error': _('Unsupported file type')})
        
        # Use Gemini manager to generate metadata from file
        is_seo_avail, seo_availability_message = get_gemini_manager().check_seo_availability()
        if not is_seo_avail:
            return JsonResponse({'success': False, 'error': seo_availability_message or _('AI service not available')})
        
        # Save file temporarily for processing
        file_extension = file_obj.name.lower().split('.')[-1] if '.' in file_obj.name else 'tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        try:
            # Generate metadata using the temporary file
            success, metadata = get_gemini_manager().generate_seo(temp_file_path, content_type)
            
            if success and metadata:
                return JsonResponse({
                    'success': True,
                    'metadata': metadata
                })
            else:
                error_msg = metadata.get('error', _('Failed to generate metadata')) if isinstance(metadata, dict) else _('Failed to generate metadata')
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
def get_r2_storage_usage(request):
    """
    Get R2 bucket storage usage statistics for admin dashboard.
    Returns cached data by default (5 minute cache).
    Use ?refresh=true to force refresh.
    """
    try:
        # Check if user has permission (staff or superuser)
        if not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'error': _('Permission denied. Staff access required.')
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


@staff_member_required 
@require_POST
def retry_r2_upload(request, content_type, meta_id):
    """
    Retry R2 upload for a specific content item.
    Args:
        content_type: 'video', 'audio', or 'pdf'
        meta_id: ID of the meta object (VideoMeta, AudioMeta, or PdfMeta)
    """
    if not request.user.is_staff:
        return JsonResponse({'error': _('Permission denied')}, status=403)
    
    try:
        # Validate content type
        if content_type not in ['video', 'audio', 'pdf']:
            return JsonResponse({'error': _('Invalid content type')}, status=400)
        
        # Get the meta object and trigger appropriate R2 upload task
        task_id = None
        
        if content_type == 'video':
            video_meta = get_object_or_404(VideoMeta, id=meta_id)
            if video_meta.r2_upload_status != 'failed':
                return JsonResponse({'error': _('R2 upload can only be retried after a failed upload.')}, status=400)
            previous_state = video_meta.r2_upload_status
            video_meta.r2_upload_status = 'pending'  # Reset status
            video_meta.r2_upload_progress = 0
            video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_video_to_r2.delay(str(meta_id))
            task_id = task_result.id
            content_item = video_meta.content_item
            
        elif content_type == 'audio':
            audio_meta = get_object_or_404(AudioMeta, id=meta_id)
            if audio_meta.r2_upload_status != 'failed':
                return JsonResponse({'error': _('R2 upload can only be retried after a failed upload.')}, status=400)
            previous_state = audio_meta.r2_upload_status
            audio_meta.r2_upload_status = 'pending'  # Reset status
            audio_meta.r2_upload_progress = 0
            audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_audio_to_r2.delay(str(meta_id))
            task_id = task_result.id
            content_item = audio_meta.content_item
            
        elif content_type == 'pdf':
            pdf_meta = get_object_or_404(PdfMeta, id=meta_id)
            if pdf_meta.r2_upload_status != 'failed':
                return JsonResponse({'error': _('R2 upload can only be retried after a failed upload.')}, status=400)
            previous_state = pdf_meta.r2_upload_status
            pdf_meta.r2_upload_status = 'pending'  # Reset status
            pdf_meta.r2_upload_progress = 0
            pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            task_result = upload_pdf_to_r2.delay(str(meta_id))
            task_id = task_result.id
            content_item = pdf_meta.content_item

        LifecycleAuditService.log_event(
            content_item=content_item,
            action_type='r2_upload_retry_requested',
            actor=request.user,
            source='admin:r2_retry',
            previous_state=previous_state,
            new_state='pending',
            message='Single-item R2 upload retry triggered from admin API',
            payload={'content_type': content_type, 'meta_id': str(meta_id), 'task_id': task_id},
        )
        
        logger.info(f"Triggered R2 upload retry for {content_type} {meta_id} (task: {task_id})")
        
        return JsonResponse({
            'success': True,
            'message': _('R2 upload retry triggered for %(type)s') % {'type': content_type},
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"R2 upload retry error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@require_POST  
def bulk_retry_r2_uploads(request):
    """
    Bulk retry R2 uploads for multiple content items.
    Expects JSON payload with list of items to retry.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': _('Permission denied')}, status=403)
    
    try:
        # Parse request data
        data = json.loads(request.body)
        items = data.get('items', [])
        
        if not items:
            return JsonResponse({'error': _('No items specified')}, status=400)
        
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
                    video_meta = VideoMeta.objects.get(id=meta_id)
                    video_meta.r2_upload_status = 'pending'
                    video_meta.r2_upload_progress = 0
                    video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_video_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    LifecycleAuditService.log_event(
                        content_item=video_meta.content_item,
                        action_type='r2_upload_retry_requested',
                        actor=request.user,
                        source='admin:r2_bulk_retry',
                        previous_state='failed',
                        new_state='pending',
                        message='Bulk R2 retry triggered for video item',
                        payload={'content_type': content_type, 'meta_id': str(meta_id), 'task_id': task_result.id},
                    )
                    
                elif content_type == 'audio':
                    audio_meta = AudioMeta.objects.get(id=meta_id)
                    audio_meta.r2_upload_status = 'pending'
                    audio_meta.r2_upload_progress = 0
                    audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_audio_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    LifecycleAuditService.log_event(
                        content_item=audio_meta.content_item,
                        action_type='r2_upload_retry_requested',
                        actor=request.user,
                        source='admin:r2_bulk_retry',
                        previous_state='failed',
                        new_state='pending',
                        message='Bulk R2 retry triggered for audio item',
                        payload={'content_type': content_type, 'meta_id': str(meta_id), 'task_id': task_result.id},
                    )
                    
                elif content_type == 'pdf':
                    pdf_meta = PdfMeta.objects.get(id=meta_id)
                    pdf_meta.r2_upload_status = 'pending'
                    pdf_meta.r2_upload_progress = 0
                    pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                    task_result = upload_pdf_to_r2.delay(str(meta_id))
                    results['task_ids'].append(task_result.id)
                    LifecycleAuditService.log_event(
                        content_item=pdf_meta.content_item,
                        action_type='r2_upload_retry_requested',
                        actor=request.user,
                        source='admin:r2_bulk_retry',
                        previous_state='failed',
                        new_state='pending',
                        message='Bulk R2 retry triggered for pdf item',
                        payload={'content_type': content_type, 'meta_id': str(meta_id), 'task_id': task_result.id},
                    )
                    
                else:
                    results['errors'].append(
                        _('Invalid content type for item %(id)s: %(type)s') % {
                            'id': meta_id,
                            'type': content_type
                        }
                    )
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
            'message': _('Triggered %(count)s R2 upload retries') % {'count': results["success_count"]},
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Bulk R2 retry error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
def get_r2_sync_status(request):
    """
    Get detailed R2 sync status statistics for monitoring dashboard.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': _('Permission denied')}, status=403)
    
    try:
        status_data = get_r2_sync_status_data()
        return JsonResponse(status_data)
        
    except Exception as e:
        logger.error(f"R2 sync status error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def get_r2_sync_status_data():
    """Helper function to get R2 sync status data"""
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


@staff_member_required
@require_POST
@csrf_protect
def api_auto_fill_metadata(request):
    """
    Trigger auto-fill action for content item(s) (SEO metadata generation).
    Supports both single and bulk operations.
    """
    try:
        data = json.loads(request.body)
        content_id = data.get('content_id')
        content_ids = data.get('content_ids')
        
        # Handle bulk operation
        if content_ids:
            task_ids = []
            success_count = 0
            
            for cid in content_ids:
                try:
                    # Verify content exists
                    content_item = ContentItem.objects.get(id=cid)
                    previous_state = content_item.seo_processing_status or 'pending'
                    content_item.seo_processing_status = 'pending'
                    content_item.save(update_fields=['seo_processing_status', 'updated_at'])
                    task = generate_seo_metadata_task.delay(str(cid))
                    task_ids.append(task.id)
                    success_count += 1
                    LifecycleAuditService.log_event(
                        content_item=content_item,
                        action_type='seo_generation_requested',
                        actor=request.user,
                        source='admin:seo_bulk_request',
                        previous_state=previous_state,
                        new_state='pending',
                        message='Bulk SEO generation requested from admin API',
                        payload={'content_id': str(content_item.id), 'task_id': task.id},
                    )
                except ContentItem.DoesNotExist:
                    logger.warning(f"Content {cid} not found for bulk SEO generation")
                    continue
            
            logger.info(f"Bulk auto-fill triggered for {success_count} items")
            
            return JsonResponse({
                'success': True,
                'message': _('SEO generation started for %(count)s item(s)') % {'count': success_count},
                'task_ids': task_ids
            })
        
        # Handle single operation
        if not content_id:
            return JsonResponse({'success': False, 'error': _('No content ID provided')})
        
        # Get the content item
        content_item = ContentItem.objects.filter(id=content_id).first()
        if not content_item:
            return JsonResponse({'success': False, 'error': _('Content not found')})

        force_regenerate = bool(data.get('force'))
        if content_item.has_seo_metadata() and content_item.seo_processing_status == 'completed' and not force_regenerate:
            return JsonResponse({
                'success': False,
                'error': _('SEO metadata already exists for this item.')
            }, status=400)

        previous_state = content_item.seo_processing_status or 'pending'
        content_item.seo_processing_status = 'pending'
        content_item.save(update_fields=['seo_processing_status', 'updated_at'])
        
        # Trigger the background task
        task = generate_seo_metadata_task.delay(str(content_id))
        LifecycleAuditService.log_event(
            content_item=content_item,
            action_type='seo_generation_requested',
            actor=request.user,
            source='admin:seo_request',
            previous_state=previous_state,
            new_state='pending',
            message='SEO generation requested from admin API',
            payload={'content_id': str(content_item.id), 'task_id': task.id},
        )
        
        logger.info(f"Auto-fill triggered for content {content_id}, task ID: {task.id}")
        
        return JsonResponse({
            'success': True,
            'message': _('Auto-fill started. SEO metadata will be generated in the background.'),
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
        return None, _('Unsupported file type')


@staff_member_required
@require_POST
@csrf_protect
def generate_metadata_only(request):
    """Generate metadata only from uploaded file (new separated endpoint)"""
    try:
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': _('File required')})
        
        # Determine content type
        content_type, error = _determine_content_type(file_obj, request.POST.get('content_type', ''))
        if error:
            return JsonResponse({'success': False, 'error': error})
        
        # Use Gemini metadata service
        metadata_service = get_gemini_metadata_service()
        if not metadata_service.is_available():
            return JsonResponse({'success': False, 'error': _('AI service not available')})
        
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
                error_msg = metadata.get('error', _('Failed to generate metadata')) if isinstance(metadata, dict) else _('Failed to generate metadata')
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            _cleanup_temp_file(temp_file_path)
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
@require_POST
@csrf_protect
def generate_seo_only(request):
    """Generate SEO metadata only from uploaded file (new separated endpoint)"""
    try:
        file_obj = request.FILES.get('file')
        if not file_obj:
            return JsonResponse({'success': False, 'error': _('File required')})
        
        # Determine content type
        content_type, error = _determine_content_type(file_obj, request.POST.get('content_type', ''))
        if error:
            return JsonResponse({'success': False, 'error': error})
        
        # Use Gemini SEO service
        seo_service = get_gemini_seo_service()
        if not seo_service.is_available():
            return JsonResponse({'success': False, 'error': _('AI service not available')})
        
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
                error_msg = seo_data.get('error', _('Failed to generate SEO metadata')) if isinstance(seo_data, dict) else _('Failed to generate SEO metadata')
                return JsonResponse({'success': False, 'error': error_msg})
                
        finally:
            _cleanup_temp_file(temp_file_path)
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@staff_member_required
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
                        return JsonResponse({'success': False, 'error': _('Invalid JSON in structured data')})
                elif isinstance(structured_data, dict):
                    content.structured_data = structured_data
                else:
                    return JsonResponse({'success': False, 'error': _('Invalid format for structured data')})
            else:
                content.structured_data = {}
            
            content.save()
            
            return JsonResponse({
                'success': True,
                'message': _('SEO data updated successfully')
            })
        
        else:
            return JsonResponse({'success': False, 'error': _('Method not allowed')}, status=405)
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
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
        
        # Build dynamic model list from DB (replaces hardcoded JS array in template)
        COLOR_PALETTE = ['primary', 'info', 'secondary', 'dark', 'warning', 'success']
        ICON_PALETTE = ['lightning-fill', 'info-circle-fill', 'shield-check', 'gear', 'bar-chart', 'activity']
        models = []
        for idx, setting in enumerate(GeminiModelSetting.objects.filter(archived_at__isnull=True).order_by('fallback_priority')):
            model_id = setting.model_key.replace('.', '_').replace('-', '_')
            position = min(idx, len(COLOR_PALETTE) - 1)
            purpose = _('Primary Model') if setting.is_default else _('Fallback Layer')
            models.append({
                'id': model_id,
                'name': setting.display_name,
                'purpose': purpose,
                'color': COLOR_PALETTE[position],
                'icon': ICON_PALETTE[position],
            })
        
        return JsonResponse({
            'success': True,
            'rate_limits': rate_limits,
            'models': models,
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


@staff_member_required
def api_gemini_reporting(request):
    """API endpoint for Gemini usage reporting queries"""
    try:
        gemini_manager = get_gemini_manager()
        report_type = request.GET.get('type', 'summary')
        days = int(request.GET.get('days', 30))
        content_item_id = request.GET.get('content_item_id')

        reporting = gemini_manager.reporting_service

        report_map = {
            'summary': lambda: reporting.summary_stats(days),
            'total_by_model': lambda: reporting.total_calls_by_model(days),
            'status_by_model': lambda: reporting.status_counts_by_model(days),
            'fallback': lambda: reporting.fallback_usage(days),
            'daily_volume': lambda: reporting.daily_volume(days),
            'hourly_volume': lambda: reporting.hourly_volume(min(days, 7)),
            'response_times': lambda: reporting.avg_response_time_by_model(days),
            'per_item': lambda: reporting.per_item_history(content_item_id) if content_item_id else [],
            'daily_token_usage': lambda: reporting.daily_token_usage(days),
            'minute_token_usage': lambda: reporting.minute_token_usage(
                request.GET.get('model_key', ''),
                timezone.now().date()
            ) if request.GET.get('model_key') else [],
        }

        result = report_map.get(report_type, report_map['summary'])()

        return JsonResponse({'success': True, 'report_type': report_type, 'data': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
def api_gemini_models(request):
    """CRUD API for Gemini model settings"""
    if request.method == 'GET':
        models_qs = GeminiModelSetting.objects.all().order_by('fallback_priority')
        data = []
        for m in models_qs:
            data.append({
                'id': str(m.id),
                'model_key': m.model_key,
                'display_name': m.display_name,
                'provider': m.provider,
                'is_enabled': m.is_enabled,
                'is_default': m.is_default,
                'fallback_priority': m.fallback_priority,
                'limit_per_minute': m.limit_per_minute,
                'limit_per_day': m.limit_per_day,
                'limit_per_month': m.limit_per_month,
                'tokens_per_minute': m.tokens_per_minute,
                'tokens_per_day': m.tokens_per_day,
                'max_input_tokens': m.max_input_tokens,
                'request_timeout_seconds': m.request_timeout_seconds,
                'notes': m.notes,
                'archived_at': m.archived_at.isoformat() if m.archived_at else None,
                'created_at': m.created_at.isoformat(),
            })
        return JsonResponse({'success': True, 'models': data})

    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            action = body.get('action')

            if action == 'toggle_enable':
                model_id = body.get('id')
                obj = get_object_or_404(GeminiModelSetting, id=model_id)
                obj.is_enabled = not obj.is_enabled
                obj.save(update_fields=['is_enabled', 'updated_at'])
                return JsonResponse({'success': True, 'is_enabled': obj.is_enabled})

            if action == 'set_default':
                model_id = body.get('id')
                GeminiModelSetting.objects.filter(is_default=True).exclude(id=model_id).update(is_default=False)
                obj = get_object_or_404(GeminiModelSetting, id=model_id)
                obj.is_default = True
                obj.is_enabled = True
                obj.save(update_fields=['is_default', 'is_enabled', 'updated_at'])
                return JsonResponse({'success': True, 'is_default': True})

            if action == 'toggle_archive':
                model_id = body.get('id')
                obj = get_object_or_404(GeminiModelSetting, id=model_id)
                if obj.archived_at:
                    obj.archived_at = None
                else:
                    from django.utils import timezone as tz
                    obj.archived_at = tz.now()
                obj.save(update_fields=['archived_at', 'updated_at'])
                return JsonResponse({'success': True, 'archived_at': obj.archived_at.isoformat() if obj.archived_at else None})

            if action == 'save':
                model_id = body.get('id')
                if model_id:
                    obj = get_object_or_404(GeminiModelSetting, id=model_id)
                else:
                    obj = GeminiModelSetting()
                obj.model_key = body.get('model_key', obj.model_key)
                obj.display_name = body.get('display_name', obj.display_name)
                obj.provider = body.get('provider', obj.provider)
                obj.fallback_priority = int(body.get('fallback_priority', obj.fallback_priority))
                obj.limit_per_minute = int(body.get('limit_per_minute', obj.limit_per_minute))
                obj.limit_per_day = int(body.get('limit_per_day', obj.limit_per_day))
                obj.limit_per_month = body.get('limit_per_month') or None
                if obj.limit_per_month is not None:
                    obj.limit_per_month = int(obj.limit_per_month)
                obj.tokens_per_minute = body.get('tokens_per_minute') or None
                if obj.tokens_per_minute is not None:
                    obj.tokens_per_minute = int(obj.tokens_per_minute)
                obj.tokens_per_day = body.get('tokens_per_day') or None
                if obj.tokens_per_day is not None:
                    obj.tokens_per_day = int(obj.tokens_per_day)
                obj.max_input_tokens = body.get('max_input_tokens') or None
                if obj.max_input_tokens is not None:
                    obj.max_input_tokens = int(obj.max_input_tokens)
                obj.request_timeout_seconds = body.get('request_timeout_seconds') or None
                if obj.request_timeout_seconds is not None:
                    obj.request_timeout_seconds = int(obj.request_timeout_seconds)
                obj.notes = body.get('notes', obj.notes)
                if body.get('is_default'):
                    GeminiModelSetting.objects.filter(is_default=True).exclude(pk=obj.pk if obj.pk else None).update(is_default=False)
                    obj.is_default = True
                obj.full_clean()
                obj.save()
                return JsonResponse({'success': True, 'id': str(obj.id)})

            if action == 'delete':
                model_id = body.get('id')
                obj = get_object_or_404(GeminiModelSetting, id=model_id)
                obj.delete()
                return JsonResponse({'success': True})

            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)


@staff_member_required
def admin_gemini_management(request):
    """Gemini Model Settings & Reporting page"""
    return render(request, 'admin/gemini_management.html')


@staff_member_required
def analytics_dashboard(request):
    """
    Analytics dashboard showing content viewing statistics.
    Displays charts and tables for content view analytics.
    Includes historical summaries and real-time events for today.
    Shows both total views and unique views (by IP).
    """
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
            total_views=Count('id'),
            unique_views=Count('ip_address', distinct=True),
        )
        today_stats_by_type = {
            stat['content_type']: {
                'total_views': stat['total_views'],
                'unique_views': stat['unique_views'],
            }
            for stat in today_stats
        }
        
        # Add today's stats to daily_stats_list
        for stat in today_stats:
            daily_stats_list.append({
                'content_type': stat['content_type'],
                'date': end_date.isoformat(),  # Convert date to ISO string
                'total_views': stat['total_views'],
                'unique_views': stat['unique_views']
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
        today_top_qs = today_events.values('content_type', 'content_id').annotate(
            total_views=Count('id'),
            unique_views=Count('ip_address', distinct=True),
        )
        
        # Combine
        combined_top_map = hist_top.copy()
        for item in today_top_qs:
            key = (item['content_type'], str(item['content_id']))
            if key in combined_top_map:
                combined_top_map[key]['total_views'] += item['total_views']
                combined_top_map[key]['unique_views'] += item['unique_views']
            else:
                combined_top_map[key] = {
                    'total_views': item['total_views'],
                    'unique_views': item['unique_views']
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
        
        for content_type, stats in today_stats_by_type.items():
            if content_type in combined_totals_map:
                combined_totals_map[content_type]['total_views'] += stats['total_views']
                combined_totals_map[content_type]['unique_views'] += stats['unique_views']
            else:
                combined_totals_map[content_type] = {
                    'total_views': stats['total_views'],
                    'unique_views': stats['unique_views']
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
        
        # HTMX partial support
        if request.headers.get('HX-Request') == 'true':
            return render(request, 'admin/partials/analytics_table.html', context)
            
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


@staff_member_required
def api_analytics_views(request):
    """
    API endpoint for analytics data in JSON format.
    Used for AJAX requests and chart rendering.
    Includes historical summaries and real-time events for today.
    """
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


@staff_member_required
def search_settings_page(request):
    """Render the search settings admin page"""
    search_service = get_search_settings_service()
    settings = search_service.get_all_settings()
    
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
    
    context = {
        'current_settings': settings,
        'available_modes': modes,
        'current_language': get_language(),
    }
    return render(request, 'admin/search_settings.html', context)


@staff_member_required
def get_search_sensitivity(request):
    """Get current search sensitivity settings (JSON API)"""
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


@staff_member_required
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
                'error': _('Mode is required')
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
            'error': _('Invalid JSON data')
        }, status=400)
    except Exception as e:
        logger.error(f"Error updating search sensitivity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
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
                'error': _('Search query is required')
            }, status=400)
        
        # Get threshold for the test mode
        search_service = get_search_settings_service()
        if test_mode == 'custom' and custom_threshold is not None:
            try:
                threshold = float(custom_threshold)
                if not 0.0 <= threshold <= 1.0:
                    return JsonResponse({
                        'success': False,
                        'error': _('Custom threshold must be between 0.0 and 1.0')
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': _('Invalid custom threshold value')
                }, status=400)
        else:
            threshold = search_service.get_threshold_for_mode(test_mode)
        
        # Use UnifiedSearchService for consistent search behavior
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
            'error': _('Invalid JSON data')
        }, status=400)
    except Exception as e:
        logger.error(f"Error testing search sensitivity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@staff_member_required
@require_POST
def api_queue_promote(request, queue_id):
    """Promote a queue item to process immediately."""
    try:
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        
        # Promote the item
        APIUploadQueueService.promote_item(str(queue_id))
        
        messages.success(
            request, 
            _('Queue item "%(file_name)s" has been promoted and will be processed immediately.') % {'file_name': queue_item.file_name}
        )
        
        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': _('Item promoted successfully')
            })
        
        # Redirect for regular requests
        return redirect('frontend_api:jobs_dashboard')
        
    except Exception as e:
        logger.error(f"Error promoting queue item {queue_id}: {e}", exc_info=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        messages.error(request, _('Error promoting item: %(error)s') % {'error': str(e)})
        return redirect('frontend_api:jobs_dashboard')


@staff_member_required
@require_POST
def api_queue_cancel(request, queue_id):
    """Cancel a queue item."""
    try:
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        
        # Cancel the item
        APIUploadQueueService.cancel_item(str(queue_id))
        
        messages.success(
            request, 
            _('Queue item "%(file_name)s" has been cancelled.') % {'file_name': queue_item.file_name}
        )
        
        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': _('Item cancelled successfully')
            })
        
        # Redirect for regular requests
        return redirect('frontend_api:jobs_dashboard')
        
    except Exception as e:
        logger.error(f"Error cancelling queue item {queue_id}: {e}", exc_info=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        messages.error(request, _('Error cancelling item: %(error)s') % {'error': str(e)})
        return redirect('frontend_api:jobs_dashboard')


@staff_member_required
def document_upload(request, content_id):
    """
    Upload supplementary document to existing ContentItem.
    AJAX endpoint for document upload.
    
    POST /dashboard/content/<uuid>/document/upload/
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': _('Method not allowed')
        }, status=405)
    
    try:
        # Ensure content item exists before attaching document
        get_object_or_404(ContentItem, id=content_id)
        
        # Get document file
        document_file = request.FILES.get('document')
        if not document_file:
            return JsonResponse({
                'success': False,
                'error': _('No document file provided')
            }, status=400)
        
        # Validate file extension
        file_ext = os.path.splitext(document_file.name)[1].lower()
        if file_ext not in ['.doc', '.docx']:
            return JsonResponse({
                'success': False,
                'error': _('Only .doc and .docx files are supported')
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
                'document_path': result.get('document_path'),
                'status': result.get('status'),
                'extraction_async': True,
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


@staff_member_required
def document_download(request, content_id):
    """
    Download supplementary document.
    
    GET /dashboard/content/<uuid>/document/download/
    """
    try:
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            messages.error(request, _('No document attached to this content'))
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
        messages.error(request, _('Error downloading document'))
        return redirect('frontend_api:content_detail', content_id=content_id)


@staff_member_required
def document_delete(request, content_id):
    """
    Delete supplementary document.
    AJAX endpoint for document deletion.
    
    DELETE /dashboard/content/<uuid>/document/delete/
    """
    if request.method not in ['POST', 'DELETE']:
        return JsonResponse({
            'success': False,
            'error': _('Method not allowed')
        }, status=405)
    
    try:
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            return JsonResponse({
                'success': False,
                'error': _('No document attached to this content')
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


@staff_member_required
def thumbnail_upload(request, content_id):
    """
    AJAX endpoint to upload/replace a thumbnail for an existing ContentItem.
    POST /dashboard/content/<content_id>/thumbnail/upload/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': _('Method not allowed')}, status=405)

    try:
        content_item = get_object_or_404(ContentItem, id=content_id)
        thumbnail_file = request.FILES.get('thumbnail') or request.FILES.get('thumbnail_file')
        if not thumbnail_file:
            return JsonResponse({'success': False, 'error': _('No thumbnail file provided')}, status=400)

        # Validate MIME
        mime_type, guessed_encoding = mimetypes.guess_type(thumbnail_file.name)
        if not mime_type or not mime_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': _('Thumbnail must be an image file')}, status=400)

        # Clean up old thumbnail if present
        try:
            if content_item.thumbnail and hasattr(content_item.thumbnail, 'path'):
                if os.path.exists(content_item.thumbnail.path):
                    os.remove(content_item.thumbnail.path)
                    logger.info(f"Deleted old local thumbnail: {content_item.thumbnail.path}")
            if content_item.r2_thumbnail_url:
                r2 = R2Service()
                if r2.use_r2:
                    r2_key = content_item.thumbnail.name if content_item.thumbnail else None
                    if r2_key:
                        try:
                            r2._r2_service.delete_file(r2_key)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Error while cleaning up old thumbnail: {e}")

        # Attach new thumbnail
        content_item.thumbnail = thumbnail_file
        content_item.r2_thumbnail_url = ''
        content_item.save(update_fields=['thumbnail', 'r2_thumbnail_url'])

        # Optionally upload to R2
        if getattr(settings, 'R2_ENABLED', False):
            try:
                r2 = R2Service()
                if r2.use_r2:
                    r2.upload_thumbnail(content_item)
            except Exception as e:
                logger.error(f"Failed to upload thumbnail to R2 for content {content_id}: {e}")

        return JsonResponse({'success': True, 'message': _('Thumbnail uploaded successfully')})

    except Exception as e:
        logger.error(f"Error uploading thumbnail for {content_id}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
def jobs_dashboard(request):
    """Unified dashboard for ProcessingJob and APIUploadQueue items."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    context = {
        'status_counts': get_jobs_counts(),
        'current_tab': request.GET.get('status', 'active'),
        'content_type_filter': request.GET.get('type', 'all'),
        'search_query': request.GET.get('search', '').strip(),
        'per_page': int(request.GET.get('per_page', 20)),
    }
    return render(request, 'admin/jobs_dashboard.html', context)


@staff_member_required
def api_jobs_list(request):
    """Return the merged job list as an HTMX partial."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    status_filter = request.GET.get('status', 'active')
    content_type_filter = request.GET.get('type', 'all')
    search_query = request.GET.get('search', '').strip()
    per_page = max(1, int(request.GET.get('per_page', 20)))
    page_number = max(1, int(request.GET.get('page', 1)))

    page_obj = get_all_jobs(
        status_filter=status_filter,
        page=page_number,
        per_page=per_page,
        content_type=content_type_filter,
        search_query=search_query,
    )

    context = {
        'jobs': page_obj.object_list,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'content_type_filter': content_type_filter,
        'search_query': search_query,
        'per_page': per_page,
    }
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/jobs_table.html', context)

    redirect_params = urlencode({
        'status': status_filter,
        'type': content_type_filter,
        'search': search_query,
        'per_page': per_page,
        'page': page_number,
    })
    return redirect(
        f"{reverse('frontend_api:jobs_dashboard')}?{redirect_params}"
    )


def _parse_admin_log_date(raw_value, end_of_day=False):
    if not raw_value:
        return None

    try:
        parsed_date = date.fromisoformat(raw_value)
    except ValueError:
        return None

    boundary = datetime.combine(parsed_date, time.max if end_of_day else time.min)
    if timezone.is_naive(boundary):
        boundary = timezone.make_aware(boundary, timezone.get_current_timezone())
    return boundary


@staff_member_required
def lifecycle_audit_logs(request):
    """Staff-only audit log browser with server-side filtering and pagination."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    action_filter = request.GET.get('action', '').strip()
    actor_filter = request.GET.get('actor', '').strip()
    state_filter = request.GET.get('state', '').strip()
    search_query = request.GET.get('q', '').strip()
    created_from = request.GET.get('from', '').strip()
    created_to = request.GET.get('to', '').strip()
    per_page = min(max(1, int(request.GET.get('per_page', 20))), 100)
    page_number = max(1, int(request.GET.get('page', 1)))

    audit_logs = ContentLifecycleAuditLog.objects.select_related('content_item', 'actor').all()

    if action_filter:
        audit_logs = audit_logs.filter(action_type__icontains=action_filter)

    if actor_filter:
        actor_query = Q(actor__username__icontains=actor_filter) | Q(actor__email__icontains=actor_filter)
        if actor_filter.isdigit():
            actor_query |= Q(actor_id=int(actor_filter))
        audit_logs = audit_logs.filter(actor_query)

    if state_filter:
        audit_logs = audit_logs.filter(Q(previous_state__icontains=state_filter) | Q(new_state__icontains=state_filter))

    if search_query:
        audit_logs = audit_logs.filter(
            Q(message__icontains=search_query)
            | Q(action_type__icontains=search_query)
            | Q(source__icontains=search_query)
            | Q(content_item__title_ar__icontains=search_query)
            | Q(content_item__title_en__icontains=search_query)
            | Q(actor__username__icontains=search_query)
            | Q(actor__email__icontains=search_query)
        )

    created_from_boundary = _parse_admin_log_date(created_from)
    created_to_boundary = _parse_admin_log_date(created_to, end_of_day=True)
    if created_from_boundary:
        audit_logs = audit_logs.filter(created_at__gte=created_from_boundary)
    if created_to_boundary:
        audit_logs = audit_logs.filter(created_at__lte=created_to_boundary)

    page_obj = Paginator(audit_logs, per_page).get_page(page_number)
    pagination = SimpleNamespace(
        has_pagination=page_obj.paginator.num_pages > 1,
        has_previous=page_obj.has_previous(),
        previous_page_number=page_obj.previous_page_number() if page_obj.has_previous() else None,
        has_next=page_obj.has_next(),
        next_page_number=page_obj.next_page_number() if page_obj.has_next() else None,
        page_range=page_obj.paginator.page_range,
        page=page_obj,
    )

    query_params = {
        'action': action_filter,
        'actor': actor_filter,
        'state': state_filter,
        'q': search_query,
        'from': created_from,
        'to': created_to,
        'per_page': per_page,
    }
    extra_params = urlencode({key: value for key, value in query_params.items() if value not in ('', None)})

    context = {
        'page_obj': page_obj,
        'pagination': pagination,
        'audit_logs': page_obj.object_list,
        'action_filter': action_filter,
        'actor_filter': actor_filter,
        'state_filter': state_filter,
        'search_query': search_query,
        'created_from': created_from,
        'created_to': created_to,
        'per_page': per_page,
        'baseUrl': reverse('frontend_api:admin_lifecycle_audit_logs'),
        'hxTarget': '#lifecycle-audit-log-table',
        'extraParams': f'&{extra_params}' if extra_params else '',
    }

    if request.headers.get('HX-Request') == 'true':
        return render(request, 'admin/partials/lifecycle_audit_log_table.html', context)

    return render(request, 'admin/lifecycle_audit_logs.html', context)


@staff_member_required
def api_jobs_stats(request):
    """Return aggregate job counts for dashboard badges."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    return JsonResponse(get_jobs_counts())


@staff_member_required
@require_POST
def api_job_cancel(request):
    """Cancel a ProcessingJob or APIUploadQueue item."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    payload = parse_request_payload(request)
    job_id = payload.get('job_id')
    source = payload.get('source')

    if not job_id or not source:
        return JsonResponse({'success': False, 'error': _('job_id and source are required')}, status=400)

    if source == 'processing_job':
        job = get_object_or_404(ProcessingJob.objects.select_related('content_item'), id=job_id)

        # Allow cancellation of stale jobs (processing > 5 h) even though the
        # normal state machine doesn't permit processing → canceled.
        from datetime import timedelta
        stale_cutoff = timezone.now() - timedelta(hours=5)
        is_stale = (job.status == 'processing' and job.updated_at < stale_cutoff)

        if not job.can_cancel() and not is_stale:
            return JsonResponse({'success': False, 'error': _('Job cannot be cancelled from its current status')}, status=400)
        previous_status = job.status

        if job.celery_task_id:
            celery_app.control.revoke(job.celery_task_id, terminate=True)

        # For stale jobs we bypass transition_to() because the state machine
        # only permits pending → canceled.
        if is_stale:
            job.status = 'canceled'
            job.failure_stage = job.current_stage
            job.failure_reason = str(_('Cancelled by admin (stale job)'))
            job.last_action_source = 'admin:jobs_api'
        else:
            job.transition_to('canceled', reason=_('Cancelled by admin'), source='admin:jobs_api')
            job.failure_stage = job.current_stage
        job.save(update_fields=['status', 'failure_stage', 'failure_reason', 'last_action_source', 'updated_at'])
        LifecycleAuditService.log_event(
            content_item=job.content_item,
            action_type='processing_job_cancelled',
            actor=request.user,
            source='admin:jobs_api',
            previous_state=previous_status,
            new_state=job.status,
            message='Processing job cancelled from jobs dashboard API',
            payload={'job_id': str(job.id)},
        )

        return JsonResponse({
            'success': True,
            'message': _('Processing job cancelled successfully'),
        })

    if source == 'api_queue':
        queue_item = get_object_or_404(APIUploadQueue, id=job_id)
        try:
            APIUploadQueueService.cancel_item(str(queue_item.id), action_source='admin:jobs_api', actor=request.user)
        except ValueError as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

        return JsonResponse({
            'success': True,
            'message': _('API queue item cancelled successfully'),
        })

    return JsonResponse({'success': False, 'error': _('Unknown job source')}, status=400)


@staff_member_required
@require_POST
def api_job_promote(request):
    """Promote a pending job so it runs immediately."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    payload = parse_request_payload(request)
    job_id = payload.get('job_id')
    source = payload.get('source')

    if not job_id or not source:
        return JsonResponse({'success': False, 'error': _('job_id and source are required')}, status=400)

    if source == 'processing_job':
        job = get_object_or_404(ProcessingJob.objects.select_related('content_item'), id=job_id)

        from datetime import timedelta
        stale_cutoff = timezone.now() - timedelta(hours=5)
        is_stale = (job.status == 'processing' and job.updated_at < stale_cutoff)

        if not job.can_promote() and not job.can_retry() and not is_stale:
            return JsonResponse({'success': False, 'error': _('Job is already running or completed')}, status=400)
        previous_status = job.status

        selected_stage = job.failure_stage or job.current_stage or 'file_processing'
        task = dispatch_processing_task(job.content_item, stage=selected_stage)
        if not task:
            return JsonResponse({'success': False, 'error': _('No matching task could be dispatched')}, status=400)

        if is_stale:
            # Stale jobs: revoke hung Celery task first, then force a fresh dispatch.
            if job.celery_task_id:
                celery_app.control.revoke(job.celery_task_id, terminate=True)
            job.status = 'processing'
            job.celery_task_id = task.id
            job.last_action_source = 'admin:jobs_api'
            job.retry_count += 1
            job.save(update_fields=['status', 'celery_task_id', 'retry_count', 'last_action_source', 'updated_at'])
        elif job.can_retry():
            job.transition_to('pending', reason=_('Retry requested by admin'), source='admin:jobs_api')
            job.retry_count += 1
            job.transition_to('processing', source='admin:jobs_api')
            job.celery_task_id = task.id
            job.save(update_fields=['status', 'celery_task_id', 'retry_count', 'last_action_source', 'updated_at'])
        else:
            job.transition_to('processing', source='admin:jobs_api')
            job.celery_task_id = task.id
            job.save(update_fields=['status', 'celery_task_id', 'retry_count', 'last_action_source', 'updated_at'])
        LifecycleAuditService.log_event(
            content_item=job.content_item,
            action_type='processing_job_promoted',
            actor=request.user,
            source='admin:jobs_api',
            previous_state=previous_status,
            new_state=job.status,
            message='Processing job promoted from jobs dashboard API',
            payload={'job_id': str(job.id), 'task_id': task.id},
        )

        return JsonResponse({
            'success': True,
            'message': _('Processing job promoted successfully'),
            'task_id': task.id,
        })

    if source == 'api_queue':
        queue_item = get_object_or_404(APIUploadQueue, id=job_id)
        try:
            APIUploadQueueService.promote_item(str(queue_item.id), action_source='admin:jobs_api', actor=request.user)
        except ValueError as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

        return JsonResponse({
            'success': True,
            'message': _('API queue item promoted successfully'),
        })

    return JsonResponse({'success': False, 'error': _('Unknown job source')}, status=400)


@staff_member_required
@require_POST
def api_job_dispatch(request):
    """Manually dispatch a processing job for a content item."""
    staff_guard = ensure_staff(request)
    if staff_guard:
        return staff_guard

    payload = parse_request_payload(request)
    content_id = payload.get('content_id')
    stage = payload.get('stage', 'full')
    force = str(payload.get('force', 'false')).lower() == 'true'

    if not content_id:
        return JsonResponse({'success': False, 'error': _('content_id is required')}, status=400)

    content_item = get_object_or_404(ContentItem, id=content_id)
    task_id, error_msg = dispatch_content_item_for_stage(content_item, stage, force=force, action_source='admin:jobs_api')

    if not task_id:
        return JsonResponse({'success': False, 'error': _(error_msg or 'No matching task could be dispatched')}, status=400)

    LifecycleAuditService.log_event(
        content_item=content_item,
        action_type='processing_job_dispatched',
        actor=request.user,
        source='admin:jobs_api',
        previous_state='',
        new_state='processing',
        message='Manual dispatch requested from jobs dashboard API',
        payload={'content_id': str(content_item.id), 'stage': stage, 'force': force, 'task_id': task_id},
    )

    return JsonResponse({
        'success': True,
        'task_id': task_id,
        'message': _('Job dispatched successfully'),
    })


