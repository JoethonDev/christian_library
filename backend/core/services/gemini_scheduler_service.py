"""
Gemini Scheduler Service
Manages deferred API request execution via Redis ZSET queue.
Supports scheduling, cancellation, backoff, and dead-letter detection.
"""
import json
import logging
import time
import uuid
from typing import Dict, List, Optional

from django.core.cache import cache

logger = logging.getLogger(__name__)

POP_DUE_JOBS_SCRIPT = """
local queue_key = KEYS[1]
local now = tonumber(ARGV[1])
local batch_size = tonumber(ARGV[2])
local jobs = redis.call('ZRANGEBYSCORE', queue_key, 0, now, 'LIMIT', 0, batch_size)
if #jobs == 0 then
    return {}
end
redis.call('ZREM', queue_key, unpack(jobs))
return jobs
"""


class GeminiSchedulerService:
    QUEUE_PREFIX = "queue:gemini:{model}"
    REQUEST_PREFIX = "gemini:scheduler:request:{request_id}"
    DEAD_LETTER_PREFIX = "gemini:scheduler:dead:{request_id}"
    MAX_BACKOFF_SECONDS = 1800  # 30 minutes
    INITIAL_BACKOFF = 60  # 1 minute
    MAX_RETRIES = 5

    def __init__(self):
        self._redis = None

    def _get_client(self):
        if self._redis is None:
            self._redis = cache.client.get_client()
        return self._redis

    def _queue_key(self, model_key: str) -> str:
        return self.QUEUE_PREFIX.replace("{model}", model_key)

    def _request_key(self, request_id: str) -> str:
        return self.REQUEST_PREFIX.replace("{request_id}", request_id)

    def _dead_letter_key(self, request_id: str) -> str:
        return self.DEAD_LETTER_PREFIX.replace("{request_id}", request_id)

    def schedule_request(
        self,
        model_key: str,
        prompt: str,
        response_schema: dict,
        delay_seconds: int = 60,
        text_content: Optional[str] = None,
        content_item_id: Optional[str] = None,
        operation_type: str = "combined",
    ) -> str:
        request_id = str(uuid.uuid4())
        execution_time = time.time() + delay_seconds

        request_data = {
            "request_id": request_id,
            "model_key": model_key,
            "prompt": prompt,
            "response_schema": response_schema,
            "text_content": text_content,
            "content_item_id": content_item_id,
            "operation_type": operation_type,
            "retry_count": 0,
            "next_delay": delay_seconds,
            "created_at": time.time(),
        }

        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            request_key = self._request_key(request_id)

            pipe = client.pipeline()
            pipe.zadd(queue_key, {request_id: execution_time})
            pipe.hset(request_key, mapping=request_data)
            pipe.expire(request_key, 86400)
            pipe.execute()

            logger.info(
                "Scheduled request %s for model %s in %.0fs",
                request_id, model_key, delay_seconds,
            )
        except Exception as e:
            logger.error("Failed to schedule request for %s: %s", model_key, e)
            raise

        return request_id

    def cancel_request(self, request_id: str, model_key: str) -> bool:
        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            request_key = self._request_key(request_id)

            pipe = client.pipeline()
            pipe.zrem(queue_key, request_id)
            pipe.delete(request_key)
            result = pipe.execute()
            return bool(result[0])
        except Exception as e:
            logger.error("Failed to cancel request %s: %s", request_id, e)
            return False

    def pop_due_jobs(self, model_key: str, batch_size: int = 10) -> List[str]:
        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            return client.eval(POP_DUE_JOBS_SCRIPT, 1, queue_key, time.time(), batch_size) or []
        except Exception as e:
            logger.error("Failed to pop due jobs for %s: %s", model_key, e)
            return []

    def get_request_data(self, request_id: str) -> Optional[Dict]:
        try:
            client = self._get_client()
            request_key = self._request_key(request_id)
            data = client.hgetall(request_key)
            if not data:
                return None
            decoded = {}
            for k, v in data.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val = v.decode("utf-8") if isinstance(v, bytes) else v
                if key in ("response_schema",):
                    decoded[key] = json.loads(val)
                elif key in ("retry_count", "next_delay"):
                    decoded[key] = int(val)
                elif key in ("created_at",):
                    decoded[key] = float(val)
                else:
                    decoded[key] = val
            return decoded
        except Exception as e:
            logger.error("Failed to get request data for %s: %s", request_id, e)
            return None

    def delete_request_data(self, request_id: str) -> None:
        try:
            client = self._get_client()
            client.delete(self._request_key(request_id))
        except Exception as e:
            logger.error("Failed to delete request data for %s: %s", request_id, e)

    def requeue_with_backoff(self, request_id: str, model_key: str, request_data: Dict) -> None:
        retry_count = request_data.get("retry_count", 0) + 1

        if retry_count > self.MAX_RETRIES:
            logger.warning("Request %s exceeded max retries, moving to dead letter", request_id)
            self._move_to_dead_letter(request_id, model_key, request_data, retry_count)
            return

        delay = min(
            self.INITIAL_BACKOFF * (2 ** (retry_count - 1)),
            self.MAX_BACKOFF_SECONDS,
        )
        execution_time = time.time() + delay

        request_data["retry_count"] = retry_count
        request_data["next_delay"] = delay

        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            request_key = self._request_key(request_id)

            pipe = client.pipeline()
            pipe.zadd(queue_key, {request_id: execution_time})
            pipe.hset(request_key, mapping=request_data)
            pipe.expire(request_key, 86400)
            pipe.execute()

            logger.info(
                "Requeued request %s for model %s with backoff %.0fs (retry %d/%d)",
                request_id, model_key, delay, retry_count, self.MAX_RETRIES,
            )
        except Exception as e:
            logger.error("Failed to requeue request %s: %s", request_id, e)

    def _move_to_dead_letter(self, request_id: str, model_key: str, request_data: Dict, retry_count: int) -> None:
        request_data["final_retry_count"] = retry_count
        request_data["dead_letter_at"] = time.time()
        try:
            client = self._get_client()
            dead_key = self._dead_letter_key(request_id)
            client.hset(dead_key, mapping=request_data)
            client.expire(dead_key, 604800)
            self.delete_request_data(request_id)
        except Exception as e:
            logger.error("Failed to move request %s to dead letter: %s", request_id, e)

    def pending_count(self, model_key: str) -> int:
        try:
            client = self._get_client()
            return client.zcard(self._queue_key(model_key)) or 0
        except Exception as e:
            logger.error("Failed to get pending count for %s: %s", model_key, e)
            return 0

    def queue_depth_by_model(self) -> Dict[str, int]:
        from apps.media_manager.models import GeminiModelSetting
        result = {}
        for setting in GeminiModelSetting.objects.filter(
            is_enabled=True, archived_at__isnull=True
        ):
            count = self.pending_count(setting.model_key)
            if count > 0:
                result[setting.model_key] = count
        return result

    def oldest_job_age(self, model_key: str) -> Optional[float]:
        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            score = client.zrange(queue_key, 0, 0, withscores=True)
            if score:
                return time.time() - score[0][1]
            return None
        except Exception as e:
            logger.error("Failed to get oldest job age for %s: %s", model_key, e)
            return None

    def clear_queue(self, model_key: str) -> int:
        try:
            client = self._get_client()
            queue_key = self._queue_key(model_key)
            count = client.zcard(queue_key)
            client.delete(queue_key)
            return count
        except Exception as e:
            logger.error("Failed to clear queue for %s: %s", model_key, e)
            return 0


_scheduler_service = None


def get_gemini_scheduler_service() -> GeminiSchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = GeminiSchedulerService()
    return _scheduler_service
