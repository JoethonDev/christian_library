"""
Celery Task Monitoring System for Admin Dashboard
Tracks background tasks and their status
"""
from typing import Dict, List, Optional
from celery import current_app
from celery.result import AsyncResult
from django.core.cache import cache
from django.utils import timezone
import json
import logging

logger = logging.getLogger(__name__)


class TaskMonitor:
    """Monitor and track Celery background tasks"""
    
    CACHE_KEY_PREFIX = "task_monitor:"
    TASK_LIST_KEY = "active_tasks"
    TASK_STATS_KEY = "task_stats"
    CACHE_TIMEOUT = 3 * 24 * 60 * 60  # 3 days
    
    @classmethod
    def register_task(cls, task_id: str, task_name: str, user_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """Register a new task for monitoring"""
        task_info = {
            'task_id': task_id,
            'task_name': task_name,
            'user_id': user_id,
            'created_at': timezone.now().isoformat(),
            'status': 'PENDING',
            'metadata': metadata or {}
        }
        
        # Add to active tasks list
        active_tasks = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", [])
        active_tasks.append(task_info)
        cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", active_tasks, cls.CACHE_TIMEOUT)
        
        # Store individual task info
        cache.set(f"{cls.CACHE_KEY_PREFIX}task:{task_id}", task_info, cls.CACHE_TIMEOUT)
        
        cls._update_stats('registered')
        logger.info(f"Registered task {task_id} ({task_name}) for monitoring")
    
    @classmethod
    def update_task_status(cls, task_id: str, status: str, result: Optional[Dict] = None, error: Optional[str] = None):
        """Update task status"""
        task_key = f"{cls.CACHE_KEY_PREFIX}task:{task_id}"
        task_info = cache.get(task_key)
        
        if task_info:
            task_info['status'] = status
            task_info['updated_at'] = timezone.now().isoformat()
            
            if result:
                task_info['result'] = result
            if error:
                task_info['error'] = error
            
            cache.set(task_key, task_info, cls.CACHE_TIMEOUT)
            cls._update_stats(status.lower())
            
            # Update in active tasks list
            active_tasks = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", [])
            for i, task in enumerate(active_tasks):
                if task['task_id'] == task_id:
                    active_tasks[i] = task_info
                    break
            cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", active_tasks, cls.CACHE_TIMEOUT)

    @classmethod
    def update_progress(cls, task_id: str, progress: int, message: str = "", step: str = ""):
        """Update task progress and optionally add a log message"""
        task_key = f"{cls.CACHE_KEY_PREFIX}task:{task_id}"
        task_info = cache.get(task_key)
        
        if task_info:
            task_info['progress'] = progress
            if step:
                task_info['current_step'] = step
            if message:
                if 'logs' not in task_info:
                    task_info['logs'] = []
                task_info['logs'].append({
                    'timestamp': timezone.now().isoformat(),
                    'message': message,
                    'progress': progress,
                    'step': step
                })
            
            task_info['updated_at'] = timezone.now().isoformat()
            cache.set(task_key, task_info, cls.CACHE_TIMEOUT)
            
            # Update in active tasks list
            active_tasks = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", [])
            for i, task in enumerate(active_tasks):
                if task['task_id'] == task_id:
                    active_tasks[i] = task_info
                    break
            cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", active_tasks, cls.CACHE_TIMEOUT)
    
    @classmethod
    def get_active_tasks(cls) -> List[Dict]:
        """Get all active tasks"""
        tasks = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", [])
        
        # Update status from Celery for each task
        updated_tasks = []
        for task in tasks:
            task_result = AsyncResult(task['task_id'])
            task['current_status'] = task_result.status
            
            # Remove completed/failed tasks older than 1 hour
            if task['current_status'] in ['SUCCESS', 'FAILURE'] and cls._is_old_task(task):
                continue
                
            updated_tasks.append(task)
        
        # Update cache with cleaned list
        cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", updated_tasks, cls.CACHE_TIMEOUT)
        return updated_tasks
    
    @classmethod
    def get_task_stats(cls) -> Dict:
        """Get task statistics for dashboard"""
        stats = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_STATS_KEY}", {
            'total_registered': 0,
            'success': 0,
            'failure': 0,
            'pending': 0,
            'retry': 0
        })
        
        # Get current active task counts
        active_tasks = cls.get_active_tasks()
        current_stats = {
            'active_tasks': len(active_tasks),
            'pending_tasks': len([t for t in active_tasks if t.get('current_status') == 'PENDING']),
            'running_tasks': len([t for t in active_tasks if t.get('current_status') in ['STARTED', 'RETRY']]),
            'recent_success': len([t for t in active_tasks if t.get('current_status') == 'SUCCESS']),
            'recent_failures': len([t for t in active_tasks if t.get('current_status') == 'FAILURE'])
        }
        
        stats.update(current_stats)
        return stats
    
    @classmethod
    def get_task_details(cls, task_id: str) -> Optional[Dict]:
        """Get detailed information about a specific task"""
        task_info = cache.get(f"{cls.CACHE_KEY_PREFIX}task:{task_id}")
        if task_info:
            # Get current status from Celery
            task_result = AsyncResult(task_id)
            task_info['current_status'] = task_result.status
            task_info['celery_result'] = task_result.result if task_result.result else None
            
        return task_info
    
    @classmethod
    def cleanup_old_tasks(cls):
        """Clean up old completed tasks"""
        active_tasks = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", [])
        current_time = timezone.now()
        
        cleaned_tasks = []
        for task in active_tasks:
            # Keep tasks that are not old or still active
            if not cls._is_old_task(task) or task.get('current_status') not in ['SUCCESS', 'FAILURE']:
                cleaned_tasks.append(task)
            else:
                # Remove individual task cache
                cache.delete(f"{cls.CACHE_KEY_PREFIX}task:{task['task_id']}")
        
        cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_LIST_KEY}", cleaned_tasks, cls.CACHE_TIMEOUT)
        logger.info(f"Cleaned up {len(active_tasks) - len(cleaned_tasks)} old tasks")
    
    @classmethod
    def _update_stats(cls, status: str):
        """Update task statistics"""
        stats = cache.get(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_STATS_KEY}", {
            'total_registered': 0,
            'success': 0,
            'failure': 0,
            'pending': 0,
            'retry': 0
        })
        
        if status == 'registered':
            stats['total_registered'] += 1
        elif status in stats:
            stats[status] += 1
            
        cache.set(f"{cls.CACHE_KEY_PREFIX}{cls.TASK_STATS_KEY}", stats, cls.CACHE_TIMEOUT * 24)  # Keep stats longer
    
    @classmethod
    def _is_old_task(cls, task: Dict) -> bool:
        """Check if task is older than 3 days"""
        try:
            created_at = timezone.datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
            return (timezone.now() - created_at).total_seconds() > 259200
        except (KeyError, ValueError):
            return True  # Consider malformed tasks as old


# Decorator to automatically track tasks
def track_task(task_name: str, user_id: Optional[str] = None, metadata: Optional[Dict] = None):
    """Decorator to automatically track Celery tasks"""
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            # Register task
            TaskMonitor.register_task(
                task_id=self.request.id,
                task_name=task_name,
                user_id=user_id,
                metadata=metadata
            )
            
            try:
                # Execute task
                result = func(self, *args, **kwargs)
                TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'result': result})
                return result
            except Exception as e:
                TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=str(e))
                raise
        return wrapper
    return decorator