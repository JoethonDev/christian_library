from django.urls import path
from django.views.generic import RedirectView
from . import views
from . import admin_views
from . import seo_views

app_name = 'frontend_api'

urlpatterns = [
    # Main pages
    path('', views.home, name='home'),
    
    # Content listing pages
    path('videos/', views.videos, name='videos'),
    path('videos/<uuid:video_uuid>/', views.video_detail, name='video_detail'),
    
    path('audios/', views.audios, name='audios'),
    path('audios/<uuid:audio_uuid>/', views.audio_detail, name='audio_detail'),
    
    path('pdfs/', views.pdfs, name='pdfs'),
    path('pdfs/<uuid:pdf_uuid>/', views.pdf_detail, name='pdf_detail'),
    
    # Search
    path('search/', views.search, name='search'),
    path('search/autocomplete/', views.search_autocomplete, name='search_autocomplete'),
    
    # Component showcase for Phase 4
    path('showcase/', views.component_showcase, name='component_showcase'),
    
    # Tag-based content filtering
    path('tags/<uuid:tag_id>/', views.tag_content, name='tag_content'),
    
    # Media player endpoints
    path('player/audio/<uuid:audio_uuid>/', views.audio_player, name='audio_player'),
    path('player/video/<uuid:video_uuid>/', views.video_player, name='video_player'),
    path('player/pdf/<uuid:pdf_uuid>/', views.pdf_player, name='pdf_player'),
    
    # Custom Admin dashboard and management views (at /en/dashboard/)
    path('dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/content/', admin_views.content_list, name='admin_content_list'),
    path('dashboard/content/<uuid:content_id>/', admin_views.content_detail, name='admin_content_detail'),
    path('dashboard/content/<uuid:content_id>/delete/', admin_views.content_delete_confirm, name='content_delete_confirm'),
    path('dashboard/content/delete/<uuid:content_id>/', admin_views.content_delete_confirm, name='admin_content_delete'),
    
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
    
    # Analytics dashboard
    path('dashboard/analytics/', admin_views.analytics_dashboard, name='analytics_dashboard'),
    path('dashboard/analytics/api/', admin_views.api_analytics_views, name='api_analytics_views'),
    
    # SEO Dashboard (at /en/dashboard/seo/)
    path('dashboard/seo/', seo_views.SEODashboardView.as_view(), name='seo_dashboard'),
    path('dashboard/seo/analytics-api/', seo_views.seo_analytics_api, name='seo_analytics_api'),
    path('dashboard/seo/content-analysis-api/', seo_views.seo_content_analysis_api, name='seo_content_analysis_api'),
    path('dashboard/seo/bulk-actions-api/', seo_views.bulk_seo_actions_api, name='bulk_seo_actions_api'),
    path('dashboard/seo/monitoring-api/', seo_views.seo_monitoring_api, name='seo_monitoring_api'),
    
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
    path('api/stats/', views.api_content_stats, name='api_content_stats'),
    path('api/track-view/', views.api_track_content_view, name='api_track_content_view'),

    path('api/toggle-status/', admin_views.api_toggle_content_status, name='api_toggle_content_status'),
    path('api/admin/r2-storage-usage/', admin_views.get_r2_storage_usage, name='api_r2_storage_usage'),
    path('api/content/<uuid:content_id>/seo/', admin_views.api_content_seo, name='api_content_seo'),
    path('api/admin/auto-fill-metadata/', admin_views.api_auto_fill_metadata, name='api_auto_fill_metadata'),
    path('api/admin/gemini-rate-limits/', admin_views.api_gemini_rate_limits, name='api_gemini_rate_limits'),
]