"""
URL patterns for System Monitor & File Manager.
Mounted at /admin/system/ in config/urls.py
"""
from django.urls import path
from .views_system import (
    SystemDashboardView,
    FileManagerView,
    FileManagerActionView,
    OrphanedFilesView,
    CacheManagerView,
)

app_name = "system_monitor"

urlpatterns = [
    path("", SystemDashboardView.as_view(), name="dashboard"),
    path("files/", FileManagerView.as_view(), name="file_manager"),
    path("files/action/", FileManagerActionView.as_view(), name="file_action"),
    path("files/orphaned/", OrphanedFilesView.as_view(), name="orphaned_files"),
    path("cache/", CacheManagerView.as_view(), name="cache_manager"),
]
