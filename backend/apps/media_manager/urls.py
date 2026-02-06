from django.urls import path
from . import views

app_name = 'media_manager'

urlpatterns = [
    # API endpoint for PDF content search
    path('api/pdf/search/', views.PDFContentSearchAPIView.as_view(), name='pdf_content_search'),
    
    # All deprecated endpoints for direct media serving, secure delivery, HLS, and embedded players have been permanently removed as of 2026-01-29.
    # See SYSTEM_OVERVIEW.md for rationale and audit trail.
]