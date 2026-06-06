import logging

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def sync_gemini_consumption(self):
    """
    Celery beat task: runs every 60 seconds.
    1. Finalize previous minute's consumption rows
    2. Sync current minute Redis counters to DB
    No daily aggregation — daily totals are computed via SQL SUM on demand.
    """
    lock_key = "gemini:consumption:sync:lock"
    if not cache.add(lock_key, 1, 45):
        logger.debug("sync_gemini_consumption: lock held by another worker, skipping")
        return

    try:
        _do_sync()
    finally:
        cache.delete(lock_key)


def _do_sync():
    from apps.media_manager.models import GeminiModelSetting, GeminiModelConsumption

    now = timezone.now()
    current_minute_slot = now.hour * 60 + now.minute
    current_date = now.date()

    # Previous minute (handles day boundary)
    if current_minute_slot == 0:
        prev_minute_slot = 1439
        prev_date = current_date - timezone.timedelta(days=1)
    else:
        prev_minute_slot = current_minute_slot - 1
        prev_date = current_date

    active_models = GeminiModelSetting.objects.filter(
        is_enabled=True, archived_at__isnull=True
    )

    for setting in active_models:
        model_key = setting.model_key
        redis_prefix = "gemini:" + model_key.replace(".", "_").replace("-", "_")

        with transaction.atomic():
            # Step 1: Finalize previous minute
            GeminiModelConsumption.objects.filter(
                model_key=model_key,
                date=prev_date,
                minute_slot=prev_minute_slot,
                is_finalized=False,
            ).select_for_update().update(is_finalized=True)

            # Step 2: Upsert current minute from Redis
            min_req_key = f"{redis_prefix}:usage:min:{now.strftime('%Y%m%d%H%M')}"
            min_tok_key = f"{redis_prefix}:tokens:min:{now.strftime('%Y%m%d%H%M')}"

            redis_requests = int(cache.get(min_req_key) or 0)
            redis_tokens = int(cache.get(min_tok_key) or 0)

            record, created = GeminiModelConsumption.objects.select_for_update().get_or_create(
                model_key=model_key,
                date=current_date,
                minute_slot=current_minute_slot,
                defaults={
                    'tokens_consumed': redis_tokens,
                    'requests_consumed': redis_requests,
                    'is_finalized': False,
                },
            )
            if not created:
                needs_update = False
                if redis_requests > record.requests_consumed:
                    record.requests_consumed = redis_requests
                    needs_update = True
                if redis_tokens > record.tokens_consumed:
                    record.tokens_consumed = redis_tokens
                    needs_update = True
                if needs_update:
                    record.save(update_fields=['tokens_consumed', 'requests_consumed', 'updated_at'])
