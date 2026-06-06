from django.urls import path, re_path
from django.views.generic import RedirectView
from . import views
from . import admin_views
from . import seo_views
from apps.users.views import LoginView as UserLoginView

app_name = 'frontend_api'

urlpatterns = [
    # Main pages
    path(
        '',
        RedirectView.as_view(
            url='/ar/home/',
            permanent=False
        ),
        name='root-redirect'
    ),
    path('home/', views.HomeView.as_view(), name='home'),

    # Content listing pages
    path('videos/', views.VideoListView.as_view(), name='videos'),
    path('videos/<uuid:video_uuid>/', views.VideoDetailView.as_view(), name='video_detail'),

    path('audios/', views.AudioListView.as_view(), name='audios'),
    path('audios/<uuid:audio_uuid>/', views.AudioDetailView.as_view(), name='audio_detail'),

    path('pdfs/', views.PdfListView.as_view(), name='pdfs'),
    path('pdfs/<uuid:pdf_uuid>/', views.PdfDetailView.as_view(), name='pdf_detail'),

    # Search
    path('search/', views.search, name='search'),
    path('search/autocomplete/', views.search_autocomplete, name='search_autocomplete'),

    # Component showcase for Phase 4
    path('showcase/', views.component_showcase, name='component_showcase'),

    # Tag-based content filtering
    path('tags/<uuid:tag_id>/', views.TagContentView.as_view(), name='tag_content'),
    
    # Media player endpoints
    path('player/audio/<uuid:audio_uuid>/', views.audio_player, name='audio_player'),
    path('player/video/<uuid:video_uuid>/', views.video_player, name='video_player'),
    path('player/pdf/<uuid:pdf_uuid>/', views.pdf_player, name='pdf_player'),
    
    # Custom Admin dashboard and management views (at /en/dashboard/)
    path('dashboard/login/', UserLoginView.as_view(), name='admin_login'),
    path('dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/content/', admin_views.content_list, name='admin_content_list'),
    path('dashboard/content/<uuid:content_id>/', admin_views.content_detail, name='admin_content_detail'),
    path('dashboard/content/<uuid:content_id>/delete/', admin_views.content_delete_confirm, name='content_delete_confirm'),
    path('dashboard/content/<uuid:content_id>/delete-local/', admin_views.delete_local_confirm, name='delete_local_confirm'),
    path('dashboard/content/delete/<uuid:content_id>/', admin_views.content_delete_confirm, name='admin_content_delete'),
    
    # Document management for content items
    path('dashboard/content/<uuid:content_id>/document/upload/', admin_views.document_upload, name='document_upload'),
    path('dashboard/content/<uuid:content_id>/document/download/', admin_views.document_download, name='document_download'),
    path('dashboard/content/<uuid:content_id>/document/delete/', admin_views.document_delete, name='document_delete'),
    path('dashboard/content/<uuid:content_id>/thumbnail/upload/', admin_views.thumbnail_upload, name='thumbnail_upload'),
    
    # Upload functionality (at /en/dashboard/upload/)
    path('dashboard/upload/', admin_views.upload_content, name='upload_content'),
    path('dashboard/upload/bulk/', admin_views.bulk_upload_page, name='bulk_upload_page'),
    # Chunked upload endpoints (initiate session, upload chunks)
    path('dashboard/upload/bulk/init/', admin_views.bulk_upload_init, name='bulk_upload_init'),
    path('dashboard/upload/bulk/chunk/', admin_views.bulk_upload_chunk, name='bulk_upload_chunk'),
    # Legacy monolithic handler removed; use chunked endpoints instead
    path('dashboard/upload/bulk/status/', admin_views.bulk_upload_status, name='bulk_upload_status'),
    path('dashboard/upload/generate/', admin_views.generate_content_metadata, name='generate_content_metadata'),
    path('dashboard/upload/generate-from-file/', admin_views.generate_metadata_from_file, name='generate_metadata_from_file'),
    path('dashboard/upload/generate-metadata-only/', admin_views.generate_metadata_only, name='generate_metadata_only'),
    path('dashboard/upload/generate-seo-only/', admin_views.generate_seo_only, name='generate_seo_only'),
        
    # System management (at /en/dashboard/system/, etc.)
    path('dashboard/system/', admin_views.system_monitor, name='system_monitor'),
    path('dashboard/system/files/', admin_views.file_manager, name='file_manager'),
    path('dashboard/system/files/action/', admin_views.file_manager_action, name='file_manager_action'),
    path('dashboard/system/files/search/', admin_views.file_manager_search, name='file_manager_search'),
    path('dashboard/system/files/info/', admin_views.file_manager_info, name='file_manager_info'),
    path('dashboard/system/files/download/', admin_views.file_manager_download, name='file_manager_download'),
    path('dashboard/system/orphaned/', admin_views.orphaned_files, name='orphaned_files'),
    path('dashboard/system/cache/', admin_views.cache_manager, name='cache_manager'),
    path('dashboard/bulk/', admin_views.bulk_operations, name='bulk_operations'),

    # Background Jobs dashboard (at /en/dashboard/jobs/)
    path('dashboard/jobs/', admin_views.jobs_dashboard, name='jobs_dashboard'),
    path('dashboard/jobs/api/list/', admin_views.api_jobs_list, name='api_jobs_list'),
    path('dashboard/jobs/api/cancel/', admin_views.api_job_cancel, name='api_job_cancel'),
    path('dashboard/jobs/api/promote/', admin_views.api_job_promote, name='api_job_promote'),
    path('dashboard/jobs/api/dispatch/', admin_views.api_job_dispatch, name='api_job_dispatch'),
    path('dashboard/jobs/api/stats/', admin_views.api_jobs_stats, name='api_jobs_stats'),

    # Content lifecycle logs dashboard
    path('dashboard/logs/', admin_views.lifecycle_audit_logs, name='admin_lifecycle_audit_logs'),
    
    path('dashboard/api-queue/<uuid:queue_id>/promote/', admin_views.api_queue_promote, name='api_queue_promote'),
    path('dashboard/api-queue/<uuid:queue_id>/cancel/', admin_views.api_queue_cancel, name='api_queue_cancel'),
    
    # Analytics dashboard
    path('dashboard/analytics/', admin_views.analytics_dashboard, name='analytics_dashboard'),
    path('dashboard/analytics/api/', admin_views.api_analytics_views, name='api_analytics_views'),
    
    # Search Sensitivity Settings
    path('dashboard/search-settings/', admin_views.search_settings_page, name='get_search_sensitivity'),
    path('dashboard/search-settings/api/', admin_views.get_search_sensitivity, name='api_get_search_sensitivity'),
    path('dashboard/search-settings/update/', admin_views.update_search_sensitivity, name='update_search_sensitivity'),
    path('dashboard/search-settings/test/', admin_views.test_search_sensitivity, name='test_search_sensitivity'),
    
    # Unified content type management (explicitly restricted to supported types)
    re_path(r'^dashboard/(?P<media_type>video|audio|pdf)/$', admin_views.media_management, name='media_management'),

    # API endpoints (NOT cached - separate from content routes)
    path('api/health/', views.api_health, name='api_health'),
    path('api/home-data/', views.api_home_data, name='api_home_data'),
    path('api/search/', views.api_global_search, name='api_global_search'),
    path('api/search/tags/', views.api_tag_search, name='api_tag_search'),
    path('api/stats/', views.api_content_stats, name='api_content_stats'),
    path('api/track-view/', views.api_track_content_view, name='api_track_content_view'),

    path('api/toggle-status/', admin_views.api_toggle_content_status, name='api_toggle_content_status'),
    path('api/admin/r2-storage-usage/', admin_views.get_r2_storage_usage, name='api_r2_storage_usage'),
    path('api/admin/r2/retry/<str:content_type>/<uuid:meta_id>/', admin_views.retry_r2_upload, name='api_r2_retry'),
    path('api/admin/r2/bulk-retry/', admin_views.bulk_retry_r2_uploads, name='api_r2_bulk_retry'),
    path('api/content/<uuid:content_id>/seo/', admin_views.api_content_seo, name='api_content_seo'),
    path('api/admin/auto-fill-metadata/', admin_views.api_auto_fill_metadata, name='api_auto_fill_metadata'),
    path('api/admin/gemini-rate-limits/', admin_views.api_gemini_rate_limits, name='api_gemini_rate_limits'),
    path('api/admin/gemini-reporting/', admin_views.api_gemini_reporting, name='api_gemini_reporting'),
    path('api/admin/gemini-models/', admin_views.api_gemini_models, name='api_gemini_models'),
    path('dashboard/gemini/', admin_views.admin_gemini_management, name='admin_gemini_management'),
]