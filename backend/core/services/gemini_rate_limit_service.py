"""
Gemini Rate Limit Service
Manages rate limits and credits for Gemini models with Redis caching.
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from datetime import datetime
from importlib import import_module
from django.core.cache import cache
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from google import genai
from apps.media_manager.models import GeminiModelSetting, GeminiModelConsumption
from .gemini_audit_helper import log_gemini_error

logger = logging.getLogger(__name__)


class ModelSelectionStrategy(ABC):
    """
    Abstract interface for model selection and fallback.
    The default implementation uses the priority chain.
    Swap by setting settings.GEMINI_MODEL_SELECTION_STRATEGY.
    """

    @abstractmethod
    def select_model(self, preferred_model: str, estimated_tokens: int = 0, **context) -> str:
        ...

    @abstractmethod
    def get_fallback(self, current_model: str, estimated_tokens: int = 0, **context) -> Optional[str]:
        ...


_strategy = None

def get_model_selection_strategy() -> ModelSelectionStrategy:
    global _strategy
    if _strategy is None:
        strategy_path = getattr(settings, 'GEMINI_MODEL_SELECTION_STRATEGY',
                                'core.services.gemini_scored_strategy.ScoredModelSelectionStrategy')
        module_path, class_name = strategy_path.rsplit('.', 1)
        module = import_module(module_path)
        cls = getattr(module, class_name)
        _strategy = cls()
    return _strategy


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

    def _get_base_limits(self, model_name: str) -> Dict:
        """Get base rate limits from DB."""
        setting = GeminiModelSetting.objects.get(model_key=model_name)
        return {
            'limit_per_minute': setting.limit_per_minute,
            'limit_per_day': setting.limit_per_day,
            'tokens_per_minute': setting.tokens_per_minute,
            'tokens_per_day': setting.tokens_per_day,
            'max_input_tokens': setting.max_input_tokens or 128000,
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
        token_min_key = f"{self.REDIS_PREFIX}:{model_key}:tokens:min:{now.strftime('%Y%m%d%H%M')}"
        token_day_key = f"{self.REDIS_PREFIX}:{model_key}:tokens:day:{now.strftime('%Y%m%d')}"

        try:
            used_minute = cache.get(minute_key, 0)
            used_day = cache.get(day_key, 0)
            used_minute = int(used_minute) if used_minute is not None else 0
            used_day = int(used_day) if used_day is not None else 0
            used_tokens_min = cache.get(token_min_key, 0)
            used_tokens_day = cache.get(token_day_key, 0)
            used_tokens_min = int(used_tokens_min) if used_tokens_min is not None else 0
            used_tokens_day = int(used_tokens_day) if used_tokens_day is not None else 0
        except (ValueError, TypeError):
            used_minute = 0
            used_day = 0
            used_tokens_min = 0
            used_tokens_day = 0

        remaining_minute = max(0, base_limits['limit_per_minute'] - used_minute)
        remaining_day = max(0, base_limits['limit_per_day'] - used_day)

        remaining_tokens_min = max(0, base_limits['tokens_per_minute'] - used_tokens_min) if base_limits['tokens_per_minute'] is not None else None
        remaining_tokens_day = max(0, base_limits['tokens_per_day'] - used_tokens_day) if base_limits['tokens_per_day'] is not None else None

        status = 'available'
        if remaining_minute <= 0 or remaining_day <= 0:
            status = 'exhausted'
        elif remaining_minute < (base_limits['limit_per_minute'] / 3) or remaining_day < (base_limits['limit_per_day'] / 5):
            status = 'limited'

        return {
            'model': model_name,
            'limit_per_minute': base_limits['limit_per_minute'],
            'limit_per_day': base_limits['limit_per_day'],
            'tokens_per_minute': base_limits['tokens_per_minute'],
            'tokens_per_day': base_limits['tokens_per_day'],
            'max_input_tokens': base_limits['max_input_tokens'],
            'used_requests_minute': used_minute,
            'used_requests_day': used_day,
            'used_tokens_minute': used_tokens_min,
            'used_tokens_day': used_tokens_day,
            'remaining_requests_minute': remaining_minute,
            'remaining_requests_day': remaining_day,
            'remaining_tokens_minute': remaining_tokens_min,
            'remaining_tokens_day': remaining_tokens_day,
            'last_updated': now.isoformat(),
            'status': status,
            'source': 'redis',
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

    def check_availability(self, model_name, operation_type='metadata', estimated_tokens=0, content_item=None):
        """
        Check availability using Redis first, fall back to DB if Redis fails.
        Logs audit event if unavailable.
        Returns (is_available, message, fallback_model).
        """
        strategy = get_model_selection_strategy()

        # ---- PATH A: Redis (fast) ----
        try:
            rate_info = self._get_rate_info_from_redis(model_name)
            is_ok, msg = self._evaluate_availability(rate_info, model_name, estimated_tokens)
            if not is_ok:
                log_gemini_error(
                    'gemini_rate_limit_exceeded',
                    model=model_name, content_item=content_item,
                    payload={k: rate_info[k] for k in rate_info if k != 'status'},
                    message=msg,
                )
            return (is_ok, msg, strategy.get_fallback(model_name, estimated_tokens) if not is_ok else None)
        except Exception as e:
            logger.warning(f"Redis rate check failed, falling back to DB: {e}")

        # ---- PATH B: Database (authoritative) ----
        try:
            rate_info = self._get_rate_info_from_db(model_name)
            if rate_info is None:
                return False, f"Model '{model_name}' not found in DB", None
            is_ok, msg = self._evaluate_availability(rate_info, model_name, estimated_tokens)
            if not is_ok:
                log_gemini_error(
                    'gemini_rate_limit_exceeded',
                    model=model_name, content_item=content_item,
                    payload={k: rate_info[k] for k in rate_info if k != 'status'},
                    message=msg,
                )
            return (is_ok, msg, strategy.get_fallback(model_name, estimated_tokens) if not is_ok else None)
        except Exception as e:
            logger.error(f"Both Redis and DB rate checks failed: {e}")
            return False, f"Rate check unavailable: {e}", None

    def record_usage(self, model_name, actual_tokens=None, content_item=None):
        """Record usage to both Redis (fast) and DB (persistent)."""
        model_key = self._normalize_model_name(model_name)
        now = timezone.now()
        minute_slot = now.hour * 60 + now.minute

        # ---- Redis (fast, atomic, best-effort) ----
        try:
            minute_key = f"{self.REDIS_PREFIX}:{model_key}:usage:min:{now.strftime('%Y%m%d%H%M')}"
            day_key = f"{self.REDIS_PREFIX}:{model_key}:usage:day:{now.strftime('%Y%m%d')}"
            self._atomic_incr(minute_key, 120)
            self._atomic_incr(day_key, 93600)
            if actual_tokens is not None:
                token_min_key = f"{self.REDIS_PREFIX}:{model_key}:tokens:min:{now.strftime('%Y%m%d%H%M')}"
                token_day_key = f"{self.REDIS_PREFIX}:{model_key}:tokens:day:{now.strftime('%Y%m%d')}"
                self._atomic_incr_by(token_min_key, actual_tokens, 120)
                self._atomic_incr_by(token_day_key, actual_tokens, 93600)
        except Exception as e:
            logger.error(f"Redis record_usage failed for {model_name}: {e}")

        # ---- DB (persistent, transactional) ----
        try:
            self._db_record_usage(
                model_name=model_name,
                tokens=actual_tokens or 0,
                requests=1,
                date=now.date(),
                minute_slot=minute_slot,
            )
        except Exception as e:
            logger.error(f"DB record_usage failed for {model_name}: {e}")

    def _atomic_incr(self, key, ttl):
        if cache.add(key, 1, ttl):
            return
        try:
            cache.incr(key)
        except (ValueError, TypeError):
            cache.set(key, 1, ttl)

    def _atomic_incr_by(self, key, amount, ttl):
        if cache.add(key, amount, ttl):
            return
        try:
            cache.incr(key, amount)
        except (ValueError, TypeError):
            current = cache.get(key) or 0
            cache.set(key, int(current) + amount, ttl)

    def _get_rate_info_from_redis(self, model_name):
        """Read consumption from Redis and DB settings for a model."""
        return self.get_rate_limit_info(model_name)

    def _get_rate_info_from_db(self, model_name):
        """Read consumption from GeminiModelConsumption for current minute/day.
           Daily totals computed via SQL SUM."""
        try:
            setting = GeminiModelSetting.objects.get(model_key=model_name)
        except GeminiModelSetting.DoesNotExist:
            return None

        now = timezone.now()
        current_minute_slot = now.hour * 60 + now.minute

        daily_agg = GeminiModelConsumption.objects.filter(
            model_key=model_name,
            date=now.date(),
        ).aggregate(
            total_tokens=models.Sum('tokens_consumed'),
            total_requests=models.Sum('requests_consumed'),
        )
        day_tokens = daily_agg['total_tokens'] or 0
        day_requests = daily_agg['total_requests'] or 0

        current_min = GeminiModelConsumption.objects.filter(
            model_key=model_name,
            date=now.date(),
            minute_slot=current_minute_slot,
        ).first()
        min_tokens = current_min.tokens_consumed if current_min else 0
        min_requests = current_min.requests_consumed if current_min else 0

        return {
            'model': model_name,
            'limit_per_minute': setting.limit_per_minute,
            'limit_per_day': setting.limit_per_day,
            'tokens_per_minute': setting.tokens_per_minute,
            'tokens_per_day': setting.tokens_per_day,
            'max_input_tokens': setting.max_input_tokens or 128000,
            'used_requests_minute': min_requests,
            'used_requests_day': day_requests,
            'used_tokens_minute': min_tokens,
            'used_tokens_day': day_tokens,
            'remaining_requests_minute': max(0, setting.limit_per_minute - min_requests),
            'remaining_requests_day': max(0, setting.limit_per_day - day_requests),
            'remaining_tokens_minute': max(0, setting.tokens_per_minute - min_tokens) if setting.tokens_per_minute is not None else None,
            'remaining_tokens_day': max(0, setting.tokens_per_day - day_tokens) if setting.tokens_per_day is not None else None,
            'status': 'available',
            'source': 'db',
        }

    def _evaluate_availability(self, rate_info, model_name, estimated_tokens):
        """Check request AND token budgets. Skips token checks if tokens_per_minute is None."""
        if rate_info['remaining_requests_minute'] < 1:
            return False, f"Minute request limit reached for {model_name}"
        if rate_info['remaining_requests_day'] < 1:
            return False, f"Daily request limit reached for {model_name}"

        if rate_info['tokens_per_minute'] is not None and estimated_tokens > 0:
            if rate_info['remaining_tokens_minute'] < estimated_tokens:
                return False, f"Minute token limit reached for {model_name} ({estimated_tokens} needed, {rate_info['remaining_tokens_minute']} remaining)"
        if rate_info['tokens_per_day'] is not None and estimated_tokens > 0:
            if rate_info['remaining_tokens_day'] < estimated_tokens:
                return False, f"Daily token limit reached for {model_name} ({estimated_tokens} needed, {rate_info['remaining_tokens_day']} remaining)"
        if rate_info['max_input_tokens'] and estimated_tokens > rate_info['max_input_tokens']:
            return False, f"Input ({estimated_tokens} tokens) exceeds {model_name} context window ({rate_info['max_input_tokens']})"

        return True, "Available"

    def _db_record_usage(self, model_name, tokens, requests, date, minute_slot):
        """Upsert GeminiModelConsumption with select_for_update."""
        with transaction.atomic():
            record, created = GeminiModelConsumption.objects.select_for_update().get_or_create(
                model_key=model_name,
                date=date,
                minute_slot=minute_slot,
                defaults={
                    'tokens_consumed': tokens,
                    'requests_consumed': requests,
                    'is_finalized': False,
                }
            )
            if not created:
                record.tokens_consumed = models.F('tokens_consumed') + tokens
                record.requests_consumed = models.F('requests_consumed') + requests
                record.save(update_fields=['tokens_consumed', 'requests_consumed', 'updated_at'])
                record.refresh_from_db()

    def _normalize_model_name(self, model_name: str) -> str:
        """Normalize model name for use as cache key"""
        return model_name.replace('.', '_').replace('-', '_')

    def _get_error_response(self, error_msg: str) -> Dict:
        """Generate error response"""
        return {
            'model': 'unknown',
            'limit_per_minute': 0,
            'limit_per_day': 0,
            'tokens_per_minute': None,
            'tokens_per_day': None,
            'max_input_tokens': 0,
            'used_requests_minute': 0,
            'used_requests_day': 0,
            'used_tokens_minute': 0,
            'used_tokens_day': 0,
            'remaining_requests_minute': 0,
            'remaining_requests_day': 0,
            'remaining_tokens_minute': None,
            'remaining_tokens_day': None,
            'last_updated': datetime.now().isoformat(),
            'status': 'error',
            'error': error_msg,
            'source': 'error',
        }


# Singleton instance
_rate_limit_service = None

def get_gemini_rate_limit_service() -> GeminiRateLimitService:
    """Get or create Gemini rate limit service singleton"""
    global _rate_limit_service
    if _rate_limit_service is None:
        _rate_limit_service = GeminiRateLimitService()
    return _rate_limit_service
