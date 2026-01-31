from django.urls import path
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
    
    # Admin dashboard and main views
    path('admin/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/content/', admin_views.content_list, name='admin_content_list'),
    path('admin/content/<uuid:content_id>/', admin_views.content_detail, name='admin_content_detail'),
    path('admin/content/<uuid:content_id>/delete/', admin_views.content_delete_confirm, name='content_delete_confirm'),
    path('admin/content/delete/<uuid:content_id>/', admin_views.content_delete_confirm, name='admin_content_delete'),
    
    # Upload functionality
    path('admin/upload/', admin_views.upload_content, name='upload_content'),
    path('admin/upload/handle/', admin_views.handle_content_upload, name='handle_upload'),
    path('admin/upload/generate/', admin_views.generate_content_metadata, name='generate_content_metadata'),
    
    # Content type specific management
    path('admin/videos/', admin_views.video_management, name='video_management'),
    path('admin/audios/', admin_views.audio_management, name='audio_management'),
    path('admin/pdfs/', admin_views.pdf_management, name='pdf_management'),
    
    # System management
    path('admin/system/', admin_views.system_monitor, name='system_monitor'),
    path('admin/bulk/', admin_views.bulk_operations, name='bulk_operations'),
    
    # SEO Dashboard (New)
    path('admin/seo/', seo_views.SEODashboardView.as_view(), name='seo_dashboard'),
    path('admin/seo/analytics-api/', seo_views.seo_analytics_api, name='seo_analytics_api'),
    path('admin/seo/content-analysis-api/', seo_views.seo_content_analysis_api, name='seo_content_analysis_api'),
    path('admin/seo/bulk-actions-api/', seo_views.bulk_seo_actions_api, name='bulk_seo_actions_api'),
    
    # Legacy admin interfaces (keeping for backward compatibility)
    path('admin-dashboard/', admin_views.admin_dashboard, name='admin_dashboard_legacy'),
    path('admin-content/', admin_views.content_list, name='admin_content_management'),
    path('admin-system/', admin_views.system_monitor, name='admin_system_monitor'),
    path('admin-bulk/', admin_views.bulk_operations, name='admin_bulk_operations'),
    
    # API endpoints
    path('api/health/', views.api_health, name='api_health'),
    path('api/home-data/', views.api_home_data, name='api_home_data'),
    path('api/search/', views.api_global_search, name='api_global_search'),
    path('api/stats/', views.api_content_stats, name='api_content_stats'),

    path('api/toggle-status/', admin_views.api_toggle_content_status, name='api_toggle_content_status'),
]