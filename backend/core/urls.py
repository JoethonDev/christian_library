"""
URLs for core functionality including monitoring, health checks, and secure media serving.
"""

from django.urls import path, re_path
from .views import monitoring
from .utils.nginx_security import SecureMediaView, SecureStreamView

app_name = 'core'

urlpatterns = [
    # Monitoring dashboard
    path('monitoring/', monitoring.MonitoringDashboardView.as_view(), name='monitoring_dashboard'),
    
    # API endpoints for real-time data
    path('api/system-metrics/', monitoring.system_metrics_api, name='system_metrics_api'),
    path('api/performance-metrics/', monitoring.performance_metrics_api, name='performance_metrics_api'),
    path('api/error-analysis/', monitoring.error_analysis_api, name='error_analysis_api'),
    path('api/alerts/', monitoring.alerts_api, name='alerts_api'),
    path('api/query-analysis/', monitoring.query_analysis_api, name='query_analysis_api'),
    path('api/health-check/', monitoring.health_check_api, name='health_check_api'),
    
    # Secure media serving with nginx X-Accel-Redirect
    re_path(r'^media/secure/(?P<file_path>.+)$', SecureMediaView.as_view(), name='secure_media'),
    re_path(r'^media/stream/(?P<file_path>.+)$', SecureStreamView.as_view(), name='secure_stream'),
]