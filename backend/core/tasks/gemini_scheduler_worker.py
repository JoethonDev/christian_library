"""
Gemini Scheduler Worker
Celery beat task that drains the Redis ZSET scheduling queue.
Runs every 5 seconds: pops due jobs, acquires lease, executes.
"""
import json
import logging

from celery import shared_task
from django.core.cache import cache
from django.apps import apps

from core.services.gemini_scheduler_service import get_gemini_scheduler_service
from core.services.gemini_lease_service import get_gemini_lease_service

logger = logging.getLogger(__name__)

MODEL_CACHE_TTL = 300


def _get_active_model_keys():
    GeminiModelSetting = apps.get_model('media_manager', 'GeminiModelSetting')
    cache_key = "gemini:scheduler:active_models"
    models = cache.get(cache_key)
    if models is not None:
        return models
    models = list(
        GeminiModelSetting.objects.filter(
            is_enabled=True, archived_at__isnull=True
        ).values_list('model_key', flat=True)
    )
    cache.set(cache_key, models, MODEL_CACHE_TTL)
    return models


@shared_task(bind=True, max_retries=1, default_retry_delay=5)
def gemini_scheduler_tick(self):
    """
    Celery beat task: runs every 5 seconds.
    Iterates active models, pops due jobs, acquires lease, executes.
    """
    lock_key = "gemini:scheduler:tick:lock"
    if not cache.add(lock_key, 1, 4):
        logger.debug("scheduler_tick: lock held, skipping")
        return

    try:
        _process_due_jobs()
    finally:
        cache.delete(lock_key)


def _process_due_jobs():
    scheduler = get_gemini_scheduler_service()
    lease_service = get_gemini_lease_service()
    model_keys = _get_active_model_keys()
    GeminiModelSetting = apps.get_model('media_manager', 'GeminiModelSetting')
    ContentItem = apps.get_model('media_manager', 'ContentItem')

    for model_key in model_keys:
        try:
            setting = GeminiModelSetting.objects.get(
                model_key=model_key, is_enabled=True, archived_at__isnull=True
            )
        except GeminiModelSetting.DoesNotExist:
            continue

        request_ids = scheduler.pop_due_jobs(model_key, batch_size=5)
        if not request_ids:
            continue

        for request_id in request_ids:
            request_data = scheduler.get_request_data(request_id)
            if not request_data:
                continue

            lease_acquired = lease_service.acquire(model_key, setting.max_concurrency)
            if not lease_acquired:
                scheduler.requeue_with_backoff(request_id, model_key, request_data)
                continue

            try:
                _execute_job(request_data, setting, ContentItem)
                scheduler.delete_request_data(request_id)
            except Exception as e:
                logger.error("Job %s failed: %s", request_id, e)
                scheduler.requeue_with_backoff(request_id, model_key, request_data)
            finally:
                lease_service.release(model_key)


def _execute_job(request_data, setting, ContentItem):
    from core.services.gemini_base_service import BaseGeminiService

    content_item = None
    content_item_id = request_data.get("content_item_id")
    if content_item_id:
        try:
            content_item = ContentItem.objects.get(id=content_item_id)
        except ContentItem.DoesNotExist:
            pass

    service = BaseGeminiService(default_model=request_data["model_key"])
    response_schema = request_data.get("response_schema", {})
    if isinstance(response_schema, str):
        response_schema = json.loads(response_schema)

    service._generate_content(
        prompt=request_data["prompt"],
        uploaded_file=None,
        response_schema=response_schema,
        model=request_data["model_key"],
        use_fallback=False,
        text_content=request_data.get("text_content"),
        content_item=content_item,
        operation_type=request_data.get("operation_type", "combined"),
    )


@shared_task(bind=True, max_retries=1, default_retry_delay=10)
def gemini_lease_stats_report(self):
    """
    Celery beat task: runs every 5 minutes.
    Reports lease statistics per model to DB for historic analysis.
    """
    from apps.media_manager.models import GeminiModelSetting

    lease_service = get_gemini_lease_service()
    cache_key = "gemini:lease:stats:report"

    if not cache.add(cache_key, 1, 240):
        logger.debug("lease_stats_report: lock held, skipping")
        return

    try:
        settings = GeminiModelSetting.objects.filter(
            is_enabled=True, archived_at__isnull=True
        )
        for setting in settings:
            active = lease_service.active_leases(setting.model_key)
            logger.info(
                "Lease stats [%s] active=%d/%d",
                setting.model_key, active, setting.max_concurrency,
            )
    except Exception as e:
        logger.error("Lease stats report failed: %s", e)
    finally:
        cache.delete(cache_key)
