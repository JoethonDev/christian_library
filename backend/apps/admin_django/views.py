"""
Django Admin Enhancement Views
Task monitoring and system integration for Django's default admin
"""
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from apps.core.task_monitor import TaskMonitor


@staff_member_required
def task_monitor(request):
    """Task monitoring dashboard for Django admin"""
    try:
        # Get all active tasks
        active_tasks = TaskMonitor.get_active_tasks()
        task_stats = TaskMonitor.get_task_stats()
        
        context = {
            'active_tasks': active_tasks,
            'task_stats': task_stats,
        }
        
        return render(request, 'admin_django/task_monitor.html', context)
        
    except Exception as e:
        context = {
            'error': str(e),
            'active_tasks': [],
            'task_stats': {},
        }
        return render(request, 'admin_django/task_monitor.html', context)


@staff_member_required
def task_detail(request, task_id):
    """Task detail view for Django admin"""
    try:
        task = TaskMonitor.get_task_details(task_id)
        
        context = {
            'task': task,
        }
        
        return render(request, 'admin_django/task_detail.html', context)
        
    except Exception as e:
        context = {
            'error': str(e),
            'task': None,
        }
        return render(request, 'admin_django/task_detail.html', context)