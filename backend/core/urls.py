"""
URLs for core functionality including monitoring and health checks.
"""

from django.urls import path
from .views import monitoring

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
]