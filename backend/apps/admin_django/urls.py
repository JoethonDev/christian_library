"""
URLs for Django Admin Enhancement (Task Monitoring)
Separate from custom admin dashboard to avoid conflicts
"""
from django.urls import path
from . import views

app_name = 'admin_django'

urlpatterns = [
    # Task Monitoring (accessible at /admin/tasks/)
    path('', views.task_monitor, name='admin_tasks'),
    path('<str:task_id>/', views.task_detail, name='admin_task_detail'),
]