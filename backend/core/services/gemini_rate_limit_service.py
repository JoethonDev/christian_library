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

logger = logging.getLogger(__name__)


class GeminiRateLimitService:
    """Service for managing Gemini API rate limits and credits"""
    
    # Model identifiers
    MODEL_3_FLASH = "gemini-3-flash-preview"
    MODEL_2_5_FLASH = "gemini-2.5-flash"
    MODEL_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    
    # Redis key prefixes
    REDIS_PREFIX = "gemini"
    CACHE_EXPIRY = 60 * 60 * 6  # 6 hours in seconds
    
    def __init__(self):
        """Initialize Gemini client"""
        try:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")
            
            self.client = genai.Client(api_key=api_key)
            self.is_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Gemini rate limit service: {e}")
            self.client = None
            self.is_initialized = False
    
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
        
        # Normalize model name
        model_key = self._normalize_model_name(model_name)
        
        # Get base limits (defaults for now)
        base_limits = self._get_base_limits(model_name)
        
        # Get current usage from Redis counters
        now = timezone.now()
        minute_key = f"{self.REDIS_PREFIX}:{model_key}:usage:min:{now.strftime('%Y%m%d%H%M')}"
        day_key = f"{self.REDIS_PREFIX}:{model_key}:usage:day:{now.strftime('%Y%m%d')}"
        
        try:
            used_minute = cache.get(minute_key, 0)
            used_day = cache.get(day_key, 0)
            
            # Ensure they are integers
            used_minute = int(used_minute) if used_minute is not None else 0
            used_day = int(used_day) if used_day is not None else 0
        except (ValueError, TypeError):
            used_minute = 0
            used_day = 0
        
        remaining_minute = max(0, base_limits['limit_per_minute'] - used_minute)
        remaining_day = max(0, base_limits['limit_per_day'] - used_day)
        
        # Determine status
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
        
        Returns:
            Dict with all models info:
            {
                'gemini_3_flash': {...},
                'gemini_2_5_flash': {...},
                'gemini_2_5_flash_lite': {...}
            }
        """
        return {
            'gemini_3_flash': self.get_rate_limit_info(self.MODEL_3_FLASH, force_refresh),
            'gemini_2_5_flash': self.get_rate_limit_info(self.MODEL_2_5_FLASH, force_refresh),
            'gemini_2_5_flash_lite': self.get_rate_limit_info(self.MODEL_2_5_FLASH_LITE, force_refresh)
        }
    
    def check_availability(self, model_name: str, operation_type: str = 'metadata') -> Tuple[bool, str, Optional[str]]:
        """
        Check if a model is available for use.
        """
        rate_info = self.get_rate_limit_info(model_name)
        
        if rate_info['status'] == 'error':
            return False, rate_info.get('error', 'Unknown error'), self._get_fallback_model(model_name)
        
        if rate_info['remaining_requests_minute'] < 1:
            return False, f"Per-minute limit reached for {model_name}", self._get_fallback_model(model_name)
            
        if rate_info['remaining_requests_day'] < 1:
            return False, f"Daily limit reached for {model_name}", self._get_fallback_model(model_name)
        
        return True, "Available", None
    
    def record_usage(self, model_name: str):
        """
        Record that a request was made to a model using atomic counters.
        """
        model_key = self._normalize_model_name(model_name)
        now = timezone.now()
        
        # Keys for minute and day counters
        # reset every minute: using %H%M
        # reset every day: using %Y%m%d
        minute_key = f"{self.REDIS_PREFIX}:{model_key}:usage:min:{now.strftime('%Y%m%d%H%M')}"
        day_key = f"{self.REDIS_PREFIX}:{model_key}:usage:day:{now.strftime('%Y%m%d')}"
        
        try:
            # Atomic increment for minute counter (expires in 2 minutes)
            if cache.get(minute_key) is None:
                cache.set(minute_key, 1, 120)
            else:
                try:
                    cache.incr(minute_key)
                except (ValueError, TypeError):
                    cache.set(minute_key, 1, 120)
            
            # Atomic increment for day counter (expires in 26 hours)
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

    def _get_base_limits(self, model_name: str) -> Dict:
        """Get base rate limits for models"""
        # Default rate limits based on Gemini model tiers (Free Tier)
        rate_limits = {
            self.MODEL_3_FLASH: {
                'limit_per_minute': 5,  # Tier 1: 5 RPM
                'limit_per_day': 20,   # Tier 1: 20 RPD
            },
            self.MODEL_2_5_FLASH: {
                'limit_per_minute': 5,  # Tier 1: 5 RPM
                'limit_per_day': 20,   # Tier 1: 20 RPD,
            },
            self.MODEL_2_5_FLASH_LITE: {
                'limit_per_minute': 10,  # Tier 1: 10 RPM (fallback)
                'limit_per_day': 20,   # Tier 1: 20 RPD
            }
        }
        return rate_limits.get(model_name, rate_limits[self.MODEL_2_5_FLASH])
    
    def _normalize_model_name(self, model_name: str) -> str:
        """Normalize model name for use as cache key"""
        return model_name.replace('.', '_').replace('-', '_')
    
    def _get_fallback_model(self, current_model: str) -> str:
        """Get fallback model for the current model"""
        return self.MODEL_2_5_FLASH_LITE
    
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
