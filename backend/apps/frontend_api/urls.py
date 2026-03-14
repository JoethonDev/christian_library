from django.urls import path
from django.views.generic import RedirectView
from . import views
from . import admin_views
from . import seo_views

app_name = 'frontend_api'

urlpatterns = [
    # Main pages
    path('', views.HomeView.as_view(), name='home'),

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
    
    # Upload functionality (at /en/dashboard/upload/)
    path('dashboard/upload/', admin_views.upload_content, name='upload_content'),
    path('dashboard/upload/handle/', admin_views.handle_content_upload, name='handle_upload'),
    path('dashboard/upload/generate/', admin_views.generate_content_metadata, name='generate_content_metadata'),
    path('dashboard/upload/generate-from-file/', admin_views.generate_metadata_from_file, name='generate_metadata_from_file'),
    path('dashboard/upload/generate-metadata-only/', admin_views.generate_metadata_only, name='generate_metadata_only'),
    path('dashboard/upload/generate-seo-only/', admin_views.generate_seo_only, name='generate_seo_only'),
    
    # Content type specific management (at /en/dashboard/videos/, etc.)
    path('dashboard/videos/', admin_views.video_management, name='video_management'),
    path('dashboard/audios/', admin_views.audio_management, name='audio_management'),
    path('dashboard/pdfs/', admin_views.pdf_management, name='pdf_management'),
    
    # System management (at /en/dashboard/system/, etc.)
    path('dashboard/system/', admin_views.system_monitor, name='system_monitor'),
    path('dashboard/bulk/', admin_views.bulk_operations, name='bulk_operations'),
    
    # API Upload Queue Management (at /en/dashboard/api-queue/)
    path('dashboard/api-queue/', admin_views.api_queue_list, name='api_queue_list'),
    path('dashboard/api-queue/<uuid:queue_id>/', admin_views.api_queue_detail, name='api_queue_detail'),
    path('dashboard/api-queue/<uuid:queue_id>/promote/', admin_views.api_queue_promote, name='api_queue_promote'),
    path('dashboard/api-queue/<uuid:queue_id>/cancel/', admin_views.api_queue_cancel, name='api_queue_cancel'),
    
    # Analytics dashboard
    path('dashboard/analytics/', admin_views.analytics_dashboard, name='analytics_dashboard'),
    path('dashboard/analytics/api/', admin_views.api_analytics_views, name='api_analytics_views'),
    
    # Search Sensitivity Settings API
    path('dashboard/search-settings/', admin_views.get_search_sensitivity, name='get_search_sensitivity'),
    path('dashboard/search-settings/update/', admin_views.update_search_sensitivity, name='update_search_sensitivity'),
    path('dashboard/search-settings/test/', admin_views.test_search_sensitivity, name='test_search_sensitivity'),
    
    # SEO Dashboard (at /en/dashboard/seo/)
    path('dashboard/seo/', seo_views.SEODashboardView.as_view(), name='seo_dashboard'),
    path('dashboard/seo/analytics-api/', seo_views.seo_analytics_api, name='seo_analytics_api'),
    path('dashboard/seo/content-analysis-api/', seo_views.seo_content_analysis_api, name='seo_content_analysis_api'),
    path('dashboard/seo/bulk-actions-api/', seo_views.bulk_seo_actions_api, name='bulk_seo_actions_api'),
    path('dashboard/seo/monitoring-api/', seo_views.seo_monitoring_api, name='seo_monitoring_api'),
    path('dashboard/seo/site-config-api/', seo_views.site_seo_api, name='site_seo_api'),
    
    # Google Re-indexing Endpoints (at /en/dashboard/seo/reindex/)
    path('dashboard/seo/reindex/', admin_views.initiate_google_reindexing, name='initiate_google_reindexing'),
    path('dashboard/seo/reindex/page/', admin_views.seo_reindex_page, name='seo_reindex_page'),
    path('dashboard/seo/reindex/status/<uuid:task_id>/', admin_views.reindex_status, name='reindex_status'),
    path('dashboard/seo/reindex/cancel/<uuid:task_id>/', admin_views.cancel_reindex, name='cancel_reindex'),
    path('dashboard/seo/reindex/history/', admin_views.reindex_history, name='reindex_history'),
    
    # Google Indexing Queue Management (at /en/dashboard/indexing-queue/)
    path('dashboard/indexing-queue/', admin_views.indexing_queue_dashboard, name='indexing_queue_dashboard'),
    path('dashboard/indexing-queue/stats/', admin_views.api_indexing_queue_stats, name='api_indexing_queue_stats'),
    path('dashboard/indexing-queue/items/', admin_views.api_indexing_queue_items, name='api_indexing_queue_items'),
    path('dashboard/indexing-queue/process/', admin_views.api_process_indexing_queue, name='api_process_indexing_queue'),
    path('dashboard/indexing-queue/revalidate/', admin_views.api_revalidate_invalid_items, name='api_revalidate_invalid_items'),
    path('dashboard/indexing-queue/retry-failed/', admin_views.api_retry_failed_items, name='api_retry_failed_items'),

    # R2 Upload Status Dashboard (at /en/dashboard/r2/)
    path('dashboard/r2/', admin_views.r2_status_dashboard, name='r2_status_dashboard'),
    path('dashboard/r2/status/', admin_views.get_r2_sync_status, name='r2_sync_status'),

    
    # Legacy admin interfaces (redirects to dashboard for backward compatibility)
    path('admin/', RedirectView.as_view(pattern_name='frontend_api:admin_dashboard'), name='admin_redirect'),
    path('admin-dashboard/', RedirectView.as_view(pattern_name='frontend_api:admin_dashboard'), name='admin_dashboard_legacy'),
    path('admin-content/', RedirectView.as_view(pattern_name='frontend_api:admin_content_list'), name='admin_content_management'),
    path('admin-system/', RedirectView.as_view(pattern_name='frontend_api:system_monitor'), name='admin_system_monitor'),
    path('admin-bulk/', RedirectView.as_view(pattern_name='frontend_api:bulk_operations'), name='admin_bulk_operations'),
    
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
]