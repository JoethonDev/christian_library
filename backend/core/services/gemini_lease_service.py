"""
Gemini Lease Service
Manages concurrent API request leases using atomic Redis operations.
Prevents model-level concurrency violations via Lua script.
"""
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

ACQUIRE_LEASE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, ttl)
end
if current <= limit then
    return 1
end
redis.call('DECR', key)
return 0
"""

RELEASE_LEASE_SCRIPT = """
local key = KEYS[1]
local current = redis.call('GET', key)
if not current then
    return 0
end
current = tonumber(current)
if current > 0 then
    return redis.call('DECR', key)
end
return 0
"""


class GeminiLeaseService:
    REDIS_PREFIX = "gemini:{model}:leases"
    LEASE_TTL_SECONDS = 300  # 5 minutes — crash safety window

    def __init__(self):
        self._redis = None

    def _get_client(self):
        if self._redis is None:
            try:
                self._redis = cache.client.get_client()
            except Exception:
                logger.error("Failed to get Redis client for lease service")
                raise
        return self._redis

    def _lease_key(self, model_key: str) -> str:
        return self.REDIS_PREFIX.replace("{model}", model_key)

    def acquire(self, model_key: str, max_concurrency: int = 3) -> bool:
        try:
            client = self._get_client()
            key = self._lease_key(model_key)
            result = client.eval(
                ACQUIRE_LEASE_SCRIPT,
                1,
                key,
                max_concurrency,
                self.LEASE_TTL_SECONDS,
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Lease acquire failed for {model_key}: {e}")
            return False

    def release(self, model_key: str) -> int:
        try:
            client = self._get_client()
            key = self._lease_key(model_key)
            result = client.eval(RELEASE_LEASE_SCRIPT, 1, key)
            return result or 0
        except Exception as e:
            logger.error(f"Lease release failed for {model_key}: {e}")
            return 0

    def active_leases(self, model_key: str) -> int:
        try:
            client = self._get_client()
            key = self._lease_key(model_key)
            val = client.get(key)
            return int(val) if val is not None else 0
        except Exception as e:
            logger.error(f"Failed to get active leases for {model_key}: {e}")
            return 0

_lease_service = None

def get_gemini_lease_service() -> GeminiLeaseService:
    global _lease_service
    if _lease_service is None:
        _lease_service = GeminiLeaseService()
    return _lease_service
