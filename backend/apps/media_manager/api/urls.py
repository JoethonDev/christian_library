"""
URL routing for RESTful Upload API.
"""
from django.urls import path
from apps.media_manager.api.views import (
    ContentUploadAPIView,
    BulkContentUploadAPIView,
    QueueStatusAPIView,
    QueueListAPIView,
    QueuePromoteAPIView,
    QueueCancelAPIView,
    DocumentUploadAPIView,
    DocumentDownloadAPIView,
    DocumentDeleteAPIView,
    DocumentMetadataAPIView,
)

app_name = 'api_upload'

urlpatterns = [
    # Upload endpoints
    path('upload/', ContentUploadAPIView.as_view(), name='upload'),
    path('upload/bulk/', BulkContentUploadAPIView.as_view(), name='bulk_upload'),
    
    # Queue management endpoints
    path('queue/', QueueListAPIView.as_view(), name='queue_list'),
    path('queue/status/<uuid:queue_id>/', QueueStatusAPIView.as_view(), name='queue_status'),
    path('queue/<uuid:queue_id>/promote/', QueuePromoteAPIView.as_view(), name='queue_promote'),
    path('queue/<uuid:queue_id>/cancel/', QueueCancelAPIView.as_view(), name='queue_cancel'),
    
    # Document management endpoints
    path('content/<uuid:content_id>/document/', DocumentMetadataAPIView.as_view(), name='document_metadata'),
    path('content/<uuid:content_id>/document/upload/', DocumentUploadAPIView.as_view(), name='document_upload'),
    path('content/<uuid:content_id>/document/download/', DocumentDownloadAPIView.as_view(), name='document_download'),
    path('content/<uuid:content_id>/document/delete/', DocumentDeleteAPIView.as_view(), name='document_delete'),
]
