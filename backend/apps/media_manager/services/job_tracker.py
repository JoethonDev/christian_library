"""Helpers for persistent processing job state updates."""

from apps.media_manager.models import ProcessingJob


def job_start(content_item_id, stage, celery_task_id=''):
    ProcessingJob.objects.update_or_create(
        content_item_id=content_item_id,
        defaults={
            'current_stage': stage,
            'status': 'processing',
            'celery_task_id': celery_task_id,
            'failure_stage': '',
            'failure_reason': '',
        },
    )


def job_fail(content_item_id, stage, reason):
    ProcessingJob.objects.update_or_create(
        content_item_id=content_item_id,
        defaults={
            'status': 'failed',
            'current_stage': stage,
            'failure_stage': stage,
            'failure_reason': str(reason)[:2000],
        },
    )


def job_advance(content_item_id, next_stage):
    ProcessingJob.objects.update_or_create(
        content_item_id=content_item_id,
        defaults={
            'current_stage': next_stage,
            'status': 'pending',
        },
    )


def job_complete(content_item_id):
    ProcessingJob.objects.update_or_create(
        content_item_id=content_item_id,
        defaults={
            'status': 'completed',
            'current_stage': 'completed',
        },
    )