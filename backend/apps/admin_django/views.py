"""
Django Admin Enhancement Views
Task monitoring and system integration for Django's default admin
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.health.task_monitor import TaskMonitor


@method_decorator(staff_member_required, name='dispatch')
class TaskMonitorView(View):
    """Task monitoring dashboard for Django admin."""

    def get(self, request):
        try:
            context = {
                'active_tasks': TaskMonitor.get_active_tasks(),
                'task_stats': TaskMonitor.get_task_stats(),
            }
        except Exception as e:
            context = {'error': str(e), 'active_tasks': [], 'task_stats': {}}
        return render(request, 'admin_django/task_monitor.html', context)


@method_decorator(staff_member_required, name='dispatch')
class TaskDetailView(View):
    """Task detail view for Django admin."""

    def get(self, request, task_id):
        try:
            context = {'task': TaskMonitor.get_task_details(task_id)}
        except Exception as e:
            context = {'error': str(e), 'task': None}
        return render(request, 'admin_django/task_detail.html', context)
