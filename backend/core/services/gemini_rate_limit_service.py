"""
Gemini Rate Limit Service
Manages rate limits and credits for Gemini models with Redis caching.
"""
import json
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from django.core.cache import cache
from django.conf import settings
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
        
        Args:
            model_name: Name of the Gemini model
            force_refresh: Force refresh from API even if cached
            
        Returns:
            Dict with rate limit info:
            {
                'limit_per_minute': int,
                'limit_per_day': int,
                'remaining_requests_minute': int,
                'remaining_requests_day': int,
                'last_updated': str (ISO format),
                'status': 'available' | 'limited' | 'exhausted' | 'error'
            }
        """
        if not self.is_initialized:
            return self._get_error_response("Service not initialized")
        
        # Normalize model name
        model_key = self._normalize_model_name(model_name)
        cache_key = f"{self.REDIS_PREFIX}:{model_key}:rate_limit"
        
        # Try to get from cache first
        if not force_refresh:
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.debug(f"Rate limit data for {model_name} retrieved from cache")
                return cached_data
        
        # Fetch from Gemini API
        try:
            rate_limit_data = self._fetch_from_gemini_api(model_name)
            
            # Cache the data
            cache.set(cache_key, rate_limit_data, self.CACHE_EXPIRY)
            logger.info(f"Rate limit data for {model_name} refreshed and cached")
            
            return rate_limit_data
            
        except Exception as e:
            logger.error(f"Error fetching rate limit for {model_name}: {e}")
            return self._get_error_response(str(e))
    
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
        
        Args:
            model_name: Name of the Gemini model
            operation_type: Type of operation ('metadata' or 'seo')
            
        Returns:
            Tuple of (is_available: bool, message: str, fallback_model: str or None)
        """
        rate_info = self.get_rate_limit_info(model_name)
        
        if rate_info['status'] == 'error':
            return False, rate_info.get('error', 'Unknown error'), self._get_fallback_model(model_name)
        
        if rate_info['status'] == 'exhausted':
            return False, f"Rate limit exhausted for {model_name}", self._get_fallback_model(model_name)
        
        if rate_info['status'] == 'limited':
            # Check if we have enough quota
            if rate_info.get('remaining_requests_minute', 0) < 1:
                return False, f"Per-minute limit reached for {model_name}", self._get_fallback_model(model_name)
            if rate_info.get('remaining_requests_day', 0) < 1:
                return False, f"Daily limit reached for {model_name}", self._get_fallback_model(model_name)
        
        return True, "Available", None
    
    def record_usage(self, model_name: str):
        """
        Record that a request was made to a model.
        Updates the cached rate limit info.
        """
        model_key = self._normalize_model_name(model_name)
        cache_key = f"{self.REDIS_PREFIX}:{model_key}:rate_limit"
        
        rate_info = cache.get(cache_key)
        if rate_info and rate_info['status'] != 'error':
            # Decrement remaining requests
            rate_info['remaining_requests_minute'] = max(0, rate_info.get('remaining_requests_minute', 0) - 1)
            rate_info['remaining_requests_day'] = max(0, rate_info.get('remaining_requests_day', 0) - 1)
            
            # Update status
            if rate_info['remaining_requests_minute'] == 0 or rate_info['remaining_requests_day'] == 0:
                rate_info['status'] = 'exhausted'
            elif rate_info['remaining_requests_minute'] < 10 or rate_info['remaining_requests_day'] < 100:
                rate_info['status'] = 'limited'
            
            # Re-cache
            cache.set(cache_key, rate_info, self.CACHE_EXPIRY)
    
    def _fetch_from_gemini_api(self, model_name: str) -> Dict:
        """
        Fetch rate limit data from Gemini API.
        
        Note: The Google Gemini API doesn't have a direct rate limit endpoint.
        We'll use sensible defaults based on the model tier and track usage.
        """
        # Default rate limits based on Gemini model tiers
        # These should be configurable in settings
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
        
        model_limits = rate_limits.get(model_name, rate_limits[self.MODEL_2_5_FLASH_LITE])
        
        return {
            'model': model_name,
            'limit_per_minute': model_limits['limit_per_minute'],
            'limit_per_day': model_limits['limit_per_day'],
            'remaining_requests_minute': model_limits['limit_per_minute'],
            'remaining_requests_day': model_limits['limit_per_day'],
            'last_updated': datetime.now().isoformat(),
            'status': 'available'
        }
    
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
