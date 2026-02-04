"""
R2 Storage Usage Service
Provides methods to fetch and cache Cloudflare R2 bucket storage usage statistics.
"""
import logging
from typing import Dict
from django.core.cache import cache
from core.services.r2_service import get_r2_service

logger = logging.getLogger(__name__)


class R2StorageService:
    """Service for fetching and managing R2 storage usage statistics"""
    
    CACHE_KEY = 'r2_storage_usage'
    CACHE_TIMEOUT = 300  # 5 minutes
    
    def __init__(self):
        """Initialize R2 storage service using modular R2Service"""
        self._r2_service = get_r2_service()
        self.enabled = self._r2_service.enabled
    
    def get_bucket_usage(self, use_cache: bool = True) -> Dict:
        """
        Get current bucket storage usage statistics.
        
        Args:
            use_cache: If True, return cached data if available (default: True)
            
        Returns:
            Dict containing:
                - success: bool
                - total_size_bytes: int (total storage used in bytes)
                - total_size_gb: float (total storage used in GB)
                - object_count: int (number of objects in bucket)
                - last_updated: str (ISO timestamp of last update)
                - error: str (error message if failed)
        """
        if not self.enabled:
            return {
                'success': False,
                'error': 'R2 storage is not enabled or not properly configured',
                'total_size_bytes': 0,
                'total_size_gb': 0.0,
                'object_count': 0
            }
        
        # Check cache first
        if use_cache:
            cached_data = cache.get(self.CACHE_KEY)
            if cached_data:
                logger.info("Returning cached R2 storage usage data")
                return cached_data
        
        # Use modular R2Service to get bucket metrics
        result = self._r2_service.get_bucket_metrics()
        
        if result['success']:
            # Add timestamp
            result['last_updated'] = self._get_current_timestamp()
            
            # Cache the result
            cache.set(self.CACHE_KEY, result, self.CACHE_TIMEOUT)
            logger.info(f"R2 storage usage: {result['total_size_gb']:.2f} GB, {result['object_count']} objects")
        
        return result
    
    def clear_cache(self):
        """Clear cached storage usage data"""
        cache.delete(self.CACHE_KEY)
        logger.info("Cleared R2 storage usage cache")
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from django.utils import timezone
        return timezone.now().isoformat()


# Singleton instance
_r2_storage_service = None


def get_r2_storage_service() -> R2StorageService:
    """Get or create singleton R2StorageService instance"""
    global _r2_storage_service
    if _r2_storage_service is None:
        _r2_storage_service = R2StorageService()
    return _r2_storage_service
