"""
DRF Views for RESTful Upload API.
"""
import os
import logging
import time
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator

from apps.media_manager.api.authentication import APISecretKeyAuthentication
from apps.media_manager.api.serializers import (
    ContentItemUploadSerializer,
    BulkContentItemUploadSerializer,
    QueueStatusSerializer,
    QueueItemSerializer,
    UploadResponseSerializer,
    BulkUploadResponseSerializer,
)
from apps.media_manager.models import APIUploadQueue
from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService

logger = logging.getLogger(__name__)


class ContentUploadAPIView(APIView):
    """
    Single file upload endpoint.
    
    POST /api/v1/upload/
    
    Supports minimal payload (file only) and full payload (file + metadata).
    Returns queue ID for status tracking.
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Handle single file upload.
        
        Request (multipart/form-data):
            - file: required
            - doc_file: optional (for PDFs)
            - title_ar, title_en, description_ar, description_en: optional
            - tags: optional (list of UUIDs)
            - seo_keywords_ar, seo_keywords_en: optional
            - transcript, notes: optional
        
        Response:
            202: Accepted (queued)
            201: Created (processing immediately)
            400: Bad Request (validation error)
        """
        start_time = time.time()
        
        # Validate request data
        serializer = ContentItemUploadSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f'Upload validation failed: {serializer.errors}')
            return Response(
                {'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        validated_data = serializer.validated_data
        file = validated_data['file']
        doc_file = validated_data.get('doc_file')
        content_type = serializer.context['detected_content_type']
        
        # Build metadata dict from optional fields
        metadata = {}
        optional_fields = [
            'title_ar', 'title_en', 'description_ar', 'description_en',
            'tags', 'seo_keywords_ar', 'seo_keywords_en', 'transcript', 'notes'
        ]
        for field in optional_fields:
            if field in validated_data:
                metadata[field] = validated_data[field]
        
        try:
            # Add to queue
            queue_item = APIUploadQueueService.add_to_queue(
                file=file,
                content_type=content_type,
                doc_file=doc_file,
                metadata=metadata
            )
            
            # Build response
            response_data = {
                'queue_id': str(queue_item.id),
                'status': queue_item.status,
                'queue_status': queue_item.queue_status,
                'queue_position': queue_item.get_queue_position(),
                'content_type': queue_item.content_type,
                'file_name': queue_item.file_name,
                'doc_file_name': doc_file.name if doc_file else None,
                'estimated_processing_time': self._estimate_processing_time(content_type)
            }
            
            # Log successful upload
            response_time = int((time.time() - start_time) * 1000)
            self._log_upload(request, status.HTTP_202_ACCEPTED, 1, file.size, response_time)
            
            # Return 201 if processing immediately, 202 if queued
            response_status = (
                status.HTTP_201_CREATED if queue_item.status == 'processing'
                else status.HTTP_202_ACCEPTED
            )
            
            logger.info(f'Upload successful: {file.name} -> queue {queue_item.id}')
            return Response(response_data, status=response_status)
        
        except ValueError as e:
            logger.error(f'Upload error: {e}')
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f'Unexpected upload error: {e}', exc_info=True)
            return Response(
                {'error': 'Internal server error during upload'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _estimate_processing_time(self, content_type):
        """Estimate processing time based on content type."""
        estimates = {
            'video': 'PT15M',  # ~15 minutes
            'audio': 'PT5M',   # ~5 minutes
            'pdf': 'PT3M',     # ~3 minutes
        }
        return estimates.get(content_type, 'PT10M')
    
    def _log_upload(self, request, status_code, files_count, total_size, response_time):
        """Log upload request to APIUploadLog."""
        try:
            from apps.media_manager.models import APIUploadLog
            import hashlib
            
            api_key = request.META.get('HTTP_X_API_SECRET_KEY', '')
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            APIUploadLog.objects.create(
                api_key_hash=key_hash,
                endpoint=request.path,
                method=request.method,
                status_code=status_code,
                files_count=files_count,
                request_size_mb=total_size / (1024 * 1024),
                response_time_ms=response_time,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        except Exception as e:
            logger.error(f'Error logging upload: {e}')
    
    def _get_client_ip(self, request):
        """Get client IP address."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return ip


class BulkContentUploadAPIView(APIView):
    """
    Bulk file upload endpoint.
    
    POST /api/v1/upload/bulk/
    
    Supports up to 20 files per request with optional shared/individual metadata.
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Handle bulk file upload.
        
        Request (multipart/form-data):
            - files: required (list, max 20)
            - doc_files: optional (list, matched by index)
            - shared_metadata: optional (JSON)
            - individual_metadata: optional (list of JSON, matched by index)
        
        Response:
            202: Accepted
            400: Bad Request
        """
        start_time = time.time()
        
        # Validate request data
        serializer = BulkContentItemUploadSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f'Bulk upload validation failed: {serializer.errors}')
            return Response(
                {'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        validated_data = serializer.validated_data
        files = validated_data['files']
        doc_files = validated_data.get('doc_files', [])
        shared_metadata = validated_data.get('shared_metadata', {})
        individual_metadata = validated_data.get('individual_metadata', [])
        
        queue_items = []
        total_size = 0
        queued_count = 0
        processing_count = 0
        
        # Process each file
        for i, file in enumerate(files):
            total_size += file.size
            
            # Detect content type
            import os
            file_ext = os.path.splitext(file.name)[1].lower()
            content_type = self._detect_content_type(file_ext)
            
            if not content_type:
                logger.warning(f'Skipping unsupported file type: {file.name}')
                continue
            
            # Get metadata for this file
            metadata = shared_metadata.copy() if shared_metadata else {}
            if individual_metadata and i < len(individual_metadata):
                metadata.update(individual_metadata[i])
            
            # Get doc file if available
            doc_file = doc_files[i] if i < len(doc_files) else None
            
            try:
                # Add to queue
                queue_item = APIUploadQueueService.add_to_queue(
                    file=file,
                    content_type=content_type,
                    doc_file=doc_file,
                    metadata=metadata
                )
                
                queue_items.append({
                    'queue_id': str(queue_item.id),
                    'status': queue_item.status,
                    'queue_status': queue_item.queue_status,
                    'queue_position': queue_item.get_queue_position(),
                    'content_type': queue_item.content_type,
                    'file_name': queue_item.file_name,
                    'doc_file_name': doc_file.name if doc_file else None,
                    'estimated_processing_time': self._estimate_processing_time(content_type)
                })
                
                if queue_item.status == 'processing':
                    processing_count += 1
                else:
                    queued_count += 1
                
            except Exception as e:
                logger.error(f'Error adding file {file.name} to queue: {e}')
                queue_items.append({
                    'file_name': file.name,
                    'error': str(e)
                })
        
        # Build response
        response_data = {
            'queue_items': queue_items,
            'total': len(queue_items),
            'queued': queued_count,
            'processing': processing_count,
        }
        
        # Log bulk upload
        response_time = int((time.time() - start_time) * 1000)
        self._log_upload(request, status.HTTP_202_ACCEPTED, len(files), total_size, response_time)
        
        logger.info(f'Bulk upload: {len(files)} files, {queued_count} queued, {processing_count} processing')
        return Response(response_data, status=status.HTTP_202_ACCEPTED)
    
    def _detect_content_type(self, file_ext):
        """Detect content type from file extension."""
        content_types = {
            '.mp4': 'video', '.mov': 'video', '.avi': 'video', '.mkv': 'video', '.webm': 'video',
            '.mp3': 'audio', '.wav': 'audio', '.m4a': 'audio', '.aac': 'audio', '.ogg': 'audio',
            '.pdf': 'pdf',
        }
        return content_types.get(file_ext.lower())
    
    def _estimate_processing_time(self, content_type):
        """Estimate processing time."""
        estimates = {
            'video': 'PT15M',
            'audio': 'PT5M',
            'pdf': 'PT3M',
        }
        return estimates.get(content_type, 'PT10M')
    
    def _log_upload(self, request, status_code, files_count, total_size, response_time):
        """Log bulk upload."""
        try:
            from apps.media_manager.models import APIUploadLog
            import hashlib
            
            api_key = request.META.get('HTTP_X_API_SECRET_KEY', '')
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            APIUploadLog.objects.create(
                api_key_hash=key_hash,
                endpoint=request.path,
                method=request.method,
                status_code=status_code,
                files_count=files_count,
                request_size_mb=total_size / (1024 * 1024),
                response_time_ms=response_time,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        except Exception as e:
            logger.error(f'Error logging bulk upload: {e}')
    
    def _get_client_ip(self, request):
        """Get client IP."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return ip


class QueueStatusAPIView(APIView):
    """
    Queue status endpoint.
    
    GET /api/v1/queue/status/<queue_id>/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, queue_id):
        """Get status of a queue item."""
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        serializer = QueueStatusSerializer(queue_item)
        return Response(serializer.data)


class QueueListAPIView(APIView):
    """
    Queue list endpoint with filtering.
    
    GET /api/v1/queue/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        List queue items with filtering and pagination.
        
        Query params:
            - status: filter by status
            - content_type: filter by content type
            - limit: items per page (default 20, max 100)
            - offset: pagination offset
        """
        # Get query params
        status_filter = request.GET.get('status')
        content_type = request.GET.get('content_type')
        limit = min(int(request.GET.get('limit', 20)), 100)
        offset = int(request.GET.get('offset', 0))
        
        # Build queryset
        queryset = APIUploadQueue.objects.all().order_by('-created_at')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        
        # Paginate
        total = queryset.count()
        queue_items = queryset[offset:offset + limit]
        
        # Serialize
        serializer = QueueItemSerializer(queue_items, many=True)
        
        return Response({
            'total': total,
            'limit': limit,
            'offset': offset,
            'results': serializer.data
        })


class QueuePromoteAPIView(APIView):
    """
    Promote queue item (admin action).
    
    POST /api/v1/queue/<queue_id>/promote/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, queue_id):
        """Promote a queue item to process immediately."""
        APIUploadQueueService.promote_item(queue_id)
        
        queue_item = get_object_or_404(APIUploadQueue, id=queue_id)
        serializer = QueueStatusSerializer(queue_item)
        
        return Response({
            'message': 'Queue item promoted',
            'item': serializer.data
        })


class QueueCancelAPIView(APIView):
    """
    Cancel queue item (admin action).
    
    DELETE /api/v1/queue/<queue_id>/cancel/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, queue_id):
        """Cancel a queue item."""
        APIUploadQueueService.cancel_item(queue_id)
        
        return Response({
            'message': 'Queue item cancelled'
        }, status=status.HTTP_204_NO_CONTENT)


class DocumentUploadAPIView(APIView):
    """
    Upload supplementary document to existing ContentItem.
    
    POST /api/v1/content/<content_id>/document/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, content_id):
        """
        Upload supplementary document.
        
        Request (multipart/form-data):
            - document: required (.doc/.docx file)
        
        Response:
            200: Success
            400: Bad Request
            404: Content not found
        """
        from apps.media_manager.services.upload_service import MediaUploadService
        from apps.media_manager.models import ContentItem
        
        # Check content item exists
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        # Get document file
        document_file = request.FILES.get('document')
        if not document_file:
            return Response(
                {'error': 'Document file is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file extension
        file_ext = os.path.splitext(document_file.name)[1].lower()
        if file_ext not in ['.doc', '.docx']:
            return Response(
                {'error': 'Only .doc and .docx files are supported'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Attach document
        upload_service = MediaUploadService()
        result = upload_service.attach_supplementary_document(content_id, document_file)
        
        if result.get('success'):
            return Response({
                'message': result.get('message'),
                'document_name': result.get('document_name'),
                'document_size': result.get('document_size'),
                'status': result.get('status')
            })
        else:
            return Response(
                {'error': result.get('error')},
                status=status.HTTP_400_BAD_REQUEST
            )


class DocumentDownloadAPIView(APIView):
    """
    Download supplementary document.
    
    GET /api/v1/content/<content_id>/document/download/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, content_id):
        """Download supplementary document."""
        from django.http import FileResponse
        from apps.media_manager.models import ContentItem
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            return Response(
                {'error': 'No document attached to this content'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            # Get file path
            file_path = content_item.supplementary_document.path
            
            # Open file and create response
            file_handle = open(file_path, 'rb')
            response = FileResponse(file_handle)
            
            # Set headers
            response['Content-Type'] = content_item.supplementary_document_type or 'application/octet-stream'
            response['Content-Disposition'] = f'attachment; filename="{content_item.supplementary_document_name}"'
            response['Content-Length'] = content_item.supplementary_document_size
            
            return response
            
        except Exception as e:
            logger.error(f"Error downloading document: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Error downloading document'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentDeleteAPIView(APIView):
    """
    Delete supplementary document.
    
    DELETE /api/v1/content/<content_id>/document/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, content_id):
        """Delete supplementary document."""
        from apps.media_manager.services.upload_service import MediaUploadService
        from apps.media_manager.models import ContentItem
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            return Response(
                {'error': 'No document attached to this content'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Delete document
        upload_service = MediaUploadService()
        result = upload_service.delete_supplementary_document(content_id)
        
        if result.get('success'):
            return Response({
                'message': result.get('message')
            }, status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(
                {'error': result.get('error')},
                status=status.HTTP_400_BAD_REQUEST
            )


class DocumentMetadataAPIView(APIView):
    """
    Get supplementary document metadata.
    
    GET /api/v1/content/<content_id>/document/
    """
    authentication_classes = [APISecretKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, content_id):
        """Get document metadata."""
        from apps.media_manager.models import ContentItem
        
        content_item = get_object_or_404(ContentItem, id=content_id)
        
        if not content_item.has_supplementary_document:
            return Response(
                {'has_document': False}
            )
        
        return Response({
            'has_document': True,
            'document_name': content_item.supplementary_document_name,
            'document_size': content_item.supplementary_document_size,
            'document_type': content_item.supplementary_document_type,
            'uploaded_at': content_item.supplementary_document_uploaded_at,
            'download_url': f'/api/v1/content/{content_id}/document/download/',
            'extracted_text_length': len(content_item.supplementary_document_text) if content_item.supplementary_document_text else 0
        })
