"""
Health check URLs for Christian Library.
"""

from django.urls import path
from . import views

app_name = 'health'

urlpatterns = [
    path('health/', views.health_check, name='health'),
    path('health/detailed/', views.detailed_health_check, name='detailed_health'),
    path('metrics/', views.system_metrics, name='metrics'),
    path('readiness/', views.readiness_probe, name='readiness'),
    path('liveness/', views.liveness_probe, name='liveness'),
]