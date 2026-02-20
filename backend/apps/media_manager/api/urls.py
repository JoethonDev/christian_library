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
]
