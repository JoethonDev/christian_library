import json

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.utils.translation import gettext_lazy as _

from apps.media_manager.models import APIUploadQueue, ProcessingJob
from apps.media_manager.tasks import extract_and_index_contentitem, generate_seo_metadata_task
from core.tasks.media_processing import (
    process_audio_compression,
    process_pdf_metadata,
    process_video_to_hls,
    upload_audio_to_r2,
    upload_pdf_to_r2,
    upload_video_to_r2,
)


def ensure_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return HttpResponseForbidden(_('Staff access required'))
    return None


def parse_request_payload(request):
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return {}
    return request.POST.dict()


def job_status_filters(status_filter):
    return {
        'active': {'processing_job': ['processing'], 'api_queue': ['processing']},
        'pending': {'processing_job': ['pending'], 'api_queue': ['pending', 'queued', 'rate_limited']},
        'canceled': {'processing_job': ['canceled'], 'api_queue': ['cancelled']},
        'completed': {'processing_job': ['completed'], 'api_queue': ['completed']},
        'failed': {'processing_job': ['failed'], 'api_queue': ['failed']},
    }.get(status_filter, {'processing_job': ['processing'], 'api_queue': ['processing']})


def dispatch_processing_task(content_item, stage='full', force=False):
    meta = content_item.get_meta_object()
    normalized_stage = stage or 'full'

    if force and normalized_stage == 'full':
        if meta:
            meta.r2_upload_status = 'pending'
            if hasattr(meta, 'processing_status'):
                meta.processing_status = 'pending'
            if hasattr(meta, 'r2_upload_progress'):
                meta.r2_upload_progress = 0
            meta.save()

        content_item.processing_status = 'pending'
        content_item.seo_processing_status = 'pending'
        content_item.seo_title_ar = ''
        content_item.seo_title_en = ''
        content_item.seo_meta_description_ar = ''
        content_item.seo_meta_description_en = ''
        content_item.seo_keywords_ar = ''
        content_item.seo_keywords_en = ''
        content_item.seo_title_suggestions = ''
        content_item.structured_data = {}
        content_item.save(update_fields=[
            'processing_status',
            'seo_processing_status',
            'seo_title_ar',
            'seo_title_en',
            'seo_meta_description_ar',
            'seo_meta_description_en',
            'seo_keywords_ar',
            'seo_keywords_en',
            'seo_title_suggestions',
            'structured_data',
        ])

    if normalized_stage in ['seo_only', 'seo_generation']:
        return generate_seo_metadata_task.apply_async(
            args=[str(content_item.id)],
            kwargs={'force_regenerate': True},
            queue='gemini',
        )

    if normalized_stage == 'text_extraction':
        return extract_and_index_contentitem.delay(str(content_item.id))

    if normalized_stage == 'r2_upload':
        if content_item.content_type == 'video' and meta:
            return upload_video_to_r2.delay(str(meta.id))
        if content_item.content_type == 'audio' and meta:
            return upload_audio_to_r2.delay(str(meta.id))
        if content_item.content_type == 'pdf' and meta:
            return upload_pdf_to_r2.delay(str(meta.id))
        return None

    if normalized_stage in ['full', 'file_processing'] and content_item.content_type == 'video' and meta:
        return process_video_to_hls.delay(str(meta.id))
    if normalized_stage in ['full', 'file_processing'] and content_item.content_type == 'audio' and meta:
        return process_audio_compression.delay(str(meta.id))
    if normalized_stage in ['full', 'file_processing'] and content_item.content_type == 'pdf' and meta:
        return process_pdf_metadata.delay(str(meta.id))

    return None


def serialize_processing_job(job):
    content_item = job.content_item
    return {
        'id': str(job.id),
        'source': 'processing_job',
        'content_id': str(content_item.id),
        'title': content_item.get_title(),
        'content_type': content_item.content_type,
        'status': job.status,
        'stage': job.current_stage,
        'celery_task_id': job.celery_task_id,
        'retry_count': job.retry_count,
        'failure_reason': job.failure_reason,
        'created_at': job.created_at,
        'updated_at': job.updated_at,
        'can_cancel': job.status in ['pending', 'processing'],
        'can_promote': job.status == 'pending',
        'can_retry': job.status == 'failed',
    }


def serialize_api_queue_item(queue_item):
    content_item = queue_item.content_item
    title = queue_item.file_name
    content_id = str(queue_item.id)

    if content_item:
        title = content_item.get_title()
        content_id = str(content_item.id)

    return {
        'id': str(queue_item.id),
        'source': 'api_queue',
        'content_id': content_id,
        'title': title,
        'content_type': queue_item.content_type,
        'status': queue_item.status,
        'stage': queue_item.queue_status,
        'celery_task_id': '',
        'retry_count': queue_item.gemini_attempts,
        'failure_reason': queue_item.error_message or '',
        'created_at': queue_item.created_at,
        'updated_at': queue_item.updated_at,
        'can_cancel': queue_item.status not in ['completed', 'cancelled'],
        'can_promote': queue_item.status in ['pending', 'queued', 'rate_limited'],
        'can_retry': queue_item.status == 'failed',
    }


def get_jobs_counts():
    return {
        'active': ProcessingJob.objects.filter(status='processing').count() + APIUploadQueue.objects.filter(status='processing').count(),
        'pending': ProcessingJob.objects.filter(status='pending').count() + APIUploadQueue.objects.filter(status__in=['pending', 'queued', 'rate_limited']).count(),
        'canceled': ProcessingJob.objects.filter(status='canceled').count() + APIUploadQueue.objects.filter(status='cancelled').count(),
        'completed': ProcessingJob.objects.filter(status='completed').count() + APIUploadQueue.objects.filter(status='completed').count(),
        'failed': ProcessingJob.objects.filter(status='failed').count() + APIUploadQueue.objects.filter(status='failed').count(),
    }


def get_all_jobs(status_filter='active', page=1, per_page=20, content_type='all', search_query=''):
    filters = job_status_filters(status_filter)

    processing_jobs = ProcessingJob.objects.select_related('content_item')
    api_queue_items = APIUploadQueue.objects.select_related('content_item')

    if content_type and content_type != 'all':
        processing_jobs = processing_jobs.filter(content_item__content_type=content_type)
        api_queue_items = api_queue_items.filter(content_type=content_type)

    if search_query:
        processing_jobs = processing_jobs.filter(
            Q(content_item__title_ar__icontains=search_query) |
            Q(content_item__title_en__icontains=search_query) |
            Q(content_item__description_ar__icontains=search_query) |
            Q(content_item__description_en__icontains=search_query)
        )
        api_queue_items = api_queue_items.filter(
            Q(file_name__icontains=search_query) |
            Q(content_item__title_ar__icontains=search_query) |
            Q(content_item__title_en__icontains=search_query)
        )

    processing_jobs = processing_jobs.filter(status__in=filters['processing_job'])
    api_queue_items = api_queue_items.filter(status__in=filters['api_queue'])

    jobs = [serialize_processing_job(job) for job in processing_jobs]
    jobs.extend(serialize_api_queue_item(item) for item in api_queue_items)
    jobs.sort(key=lambda job: job['updated_at'] or job['created_at'], reverse=True)

    paginator = Paginator(jobs, per_page)
    return paginator.get_page(page)


def dispatch_content_item_for_stage(content_item, stage):
    job, _ = ProcessingJob.objects.get_or_create(content_item=content_item)
    current_stage = {
        'full': 'file_processing',
        'file_processing': 'file_processing',
        'r2_upload': 'r2_upload',
        'seo_only': 'seo_generation',
        'seo_generation': 'seo_generation',
        'text_extraction': 'text_extraction',
    }.get(stage, 'file_processing')

    job.status = 'pending'
    job.current_stage = current_stage
    job.failure_stage = ''
    job.failure_reason = ''
    job.celery_task_id = ''
    job.save(update_fields=['status', 'current_stage', 'failure_stage', 'failure_reason', 'celery_task_id', 'updated_at'])

    task = dispatch_processing_task(content_item, stage=stage)
    if task:
        job.celery_task_id = task.id
        job.status = 'processing'
        job.save(update_fields=['status', 'celery_task_id', 'updated_at'])
        return task.id

    return ''
