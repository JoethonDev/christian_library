"""
Management command to monitor and clean up task tracking system
"""
from django.core.management.base import BaseCommand
from apps.core.task_monitor import TaskMonitor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Monitor and clean up task tracking system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up old completed tasks',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show task statistics',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List active tasks',
        )

    def handle(self, *args, **options):
        if options['cleanup']:
            self.stdout.write('Cleaning up old tasks...')
            TaskMonitor.cleanup_old_tasks()
            self.stdout.write(
                self.style.SUCCESS('Successfully cleaned up old tasks')
            )

        if options['stats']:
            stats = TaskMonitor.get_task_stats()
            self.stdout.write('\\n=== Task Statistics ===')
            for key, value in stats.items():
                self.stdout.write(f'{key}: {value}')

        if options['list']:
            active_tasks = TaskMonitor.get_active_tasks()
            self.stdout.write(f'\\n=== Active Tasks ({len(active_tasks)}) ===')
            for task in active_tasks:
                status = task.get('current_status', 'UNKNOWN')
                self.stdout.write(
                    f"ID: {task['task_id'][:8]}... | "
                    f"Name: {task['task_name']} | "
                    f"Status: {status} | "
                    f"Created: {task.get('created_at', 'Unknown')}"
                )

        if not any([options['cleanup'], options['stats'], options['list']]):
            self.stdout.write('Use --cleanup, --stats, or --list to perform actions')
            self.stdout.write('Run with --help for more options')