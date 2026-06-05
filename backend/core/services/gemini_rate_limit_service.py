"""
Gemini Rate Limit Service
Manages rate limits and credits for Gemini models with Redis caching.
"""
import json
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from google import genai
from apps.media_manager.models import GeminiModelSetting

logger = logging.getLogger(__name__)


class GeminiRateLimitService:
    """Service for managing Gemini API rate limits and credits"""

    REDIS_PREFIX = "gemini"
    CACHE_EXPIRY = 60 * 60 * 6  # 6 hours in seconds

    def __init__(self):
        """Initialize Gemini client"""
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        self.client = genai.Client(api_key=api_key)
        self.is_initialized = True

    def _get_active_models(self):
        """Return all enabled, non-archived models ordered by fallback_priority."""
        return GeminiModelSetting.objects.filter(
            is_enabled=True, archived_at__isnull=True
        ).order_by('fallback_priority')

    def _get_base_limits(self, model_name: str) -> Dict:
        """Get base rate limits from DB."""
        setting = GeminiModelSetting.objects.get(model_key=model_name)
        return {
            'limit_per_minute': setting.limit_per_minute,
            'limit_per_day': setting.limit_per_day,
        }

    def get_rate_limit_info(self, model_name: str, force_refresh: bool = False) -> Dict:
        """
        Get rate limit information for a specific model.
        Uses Redis counters for real-time tracking.

        Args:
            model_name: Name of the Gemini model
            force_refresh: Force refresh from API even if cached (not used with counters)

        Returns:
            Dict with rate limit info
        """
        if not self.is_initialized:
            return self._get_error_response("Service not initialized")

        model_key = self._normalize_model_name(model_name)

        try:
            base_limits = self._get_base_limits(model_name)
        except GeminiModelSetting.DoesNotExist:
            return self._get_error_response(f"Model '{model_name}' not found in settings")

        now = timezone.now()
        minute_key = f"{self.REDIS_PREFIX}:{model_key}:usage:min:{now.strftime('%Y%m%d%H%M')}"
        day_key = f"{self.REDIS_PREFIX}:{model_key}:usage:day:{now.strftime('%Y%m%d')}"

        try:
            used_minute = cache.get(minute_key, 0)
            used_day = cache.get(day_key, 0)
            used_minute = int(used_minute) if used_minute is not None else 0
            used_day = int(used_day) if used_day is not None else 0
        except (ValueError, TypeError):
            used_minute = 0
            used_day = 0

        remaining_minute = max(0, base_limits['limit_per_minute'] - used_minute)
        remaining_day = max(0, base_limits['limit_per_day'] - used_day)

        status = 'available'
        if remaining_minute <= 0 or remaining_day <= 0:
            status = 'exhausted'
        elif remaining_minute < (base_limits['limit_per_minute'] / 3) or remaining_day < (base_limits['limit_per_day'] / 5):
            status = 'limited'

        return {
            'model': model_name,
            'limit_per_minute': base_limits['limit_per_minute'],
            'limit_per_day': base_limits['limit_per_day'],
            'remaining_requests_minute': remaining_minute,
            'remaining_requests_day': remaining_day,
            'last_updated': now.isoformat(),
            'status': status
        }

    def get_all_models_info(self, force_refresh: bool = False) -> Dict:
        """
        Get rate limit information for all configured models.
        Iterates over DB rows.
        """
        result = {}
        for setting in GeminiModelSetting.objects.filter(archived_at__isnull=True):
            info = self.get_rate_limit_info(setting.model_key, force_refresh)
            info['display_name'] = setting.display_name
            info['is_enabled'] = setting.is_enabled
            info['is_default'] = setting.is_default
            key = setting.model_key.replace('.', '_').replace('-', '_')
            result[key] = info
        return result

    def check_availability(self, model_name: str, operation_type: str = 'metadata') -> Tuple[bool, str, Optional[str]]:
        """Check if a model is available for use."""
        rate_info = self.get_rate_limit_info(model_name)

        if rate_info['status'] == 'error':
            return False, rate_info.get('error', 'Unknown error'), self._get_fallback(model_name)

        if rate_info['remaining_requests_minute'] < 1:
            return False, f"Per-minute limit reached for {model_name}", self._get_fallback(model_name)

        if rate_info['remaining_requests_day'] < 1:
            return False, f"Daily limit reached for {model_name}", self._get_fallback(model_name)

        return True, "Available", None

    def record_usage(self, model_name: str):
        """Record that a request was made to a model using atomic counters."""
        model_key = self._normalize_model_name(model_name)
        now = timezone.now()

        minute_key = f"{self.REDIS_PREFIX}:{model_key}:usage:min:{now.strftime('%Y%m%d%H%M')}"
        day_key = f"{self.REDIS_PREFIX}:{model_key}:usage:day:{now.strftime('%Y%m%d')}"

        try:
            if cache.get(minute_key) is None:
                cache.set(minute_key, 1, 120)
            else:
                try:
                    cache.incr(minute_key)
                except (ValueError, TypeError):
                    cache.set(minute_key, 1, 120)

            if cache.get(day_key) is None:
                cache.set(day_key, 1, 93600)
            else:
                try:
                    cache.incr(day_key)
                except (ValueError, TypeError):
                    cache.set(day_key, 1, 93600)

            logger.info(f"Recorded usage for {model_name}. Keys: {minute_key}, {day_key}")
        except Exception as e:
            logger.error(f"Error recording usage for {model_name}: {e}")

    def _normalize_model_name(self, model_name: str) -> str:
        """Normalize model name for use as cache key"""
        return model_name.replace('.', '_').replace('-', '_')

    def _get_fallback(self, current_model: str) -> Optional[str]:
        """
        Find the next eligible enabled model by fallback_priority.
        Returns None if no fallback is available.
        """
        for setting in self._get_active_models():
            if setting.model_key == current_model:
                continue
            info = self.get_rate_limit_info(setting.model_key)
            if info['status'] != 'error' and info['remaining_requests_minute'] > 0 and info['remaining_requests_day'] > 0:
                return setting.model_key
        return None

    def _get_error_response(self, error_msg: str) -> Dict:
        """Generate error response"""
        return {
            'model': 'unknown',
            'limit_per_minute': 0,
            'limit_per_day': 0,
            'remaining_requests_minute': 0,
            'remaining_requests_day': 0,
            'last_updated': datetime.now().isoformat(),
            'status': 'error',
            'error': error_msg
        }


# Singleton instance
_rate_limit_service = None

def get_gemini_rate_limit_service() -> GeminiRateLimitService:
    """Get or create Gemini rate limit service singleton"""
    global _rate_limit_service
    if _rate_limit_service is None:
        _rate_limit_service = GeminiRateLimitService()
    return _rate_limit_service
