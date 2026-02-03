"""
R2 Storage Usage Service
Provides methods to fetch and cache Cloudflare R2 bucket storage usage statistics.
"""
import boto3
import logging
from typing import Dict, Optional
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class R2StorageService:
    """Service for fetching and managing R2 storage usage statistics"""
    
    CACHE_KEY = 'r2_storage_usage'
    CACHE_TIMEOUT = 300  # 5 minutes
    
    def __init__(self):
        """Initialize R2 storage service with boto3 client"""
        self.enabled = getattr(settings, 'R2_ENABLED', False)
        self.client = None
        
        if self.enabled:
            try:
                # Validate required settings
                required_settings = ['R2_BUCKET_NAME', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_ENDPOINT_URL']
                for setting in required_settings:
                    if not getattr(settings, setting, None):
                        logger.warning(f"R2 setting {setting} not configured")
                        self.enabled = False
                        return
                
                # Initialize boto3 S3 client for R2
                self.client = boto3.client(
                    's3',
                    endpoint_url=settings.R2_ENDPOINT_URL,
                    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, 'R2_REGION_NAME', 'auto')
                )
                self.bucket_name = settings.R2_BUCKET_NAME
                logger.info("R2 storage service initialized successfully")
                
            except Exception as e:
                logger.error(f"Failed to initialize R2 storage service: {e}")
                self.enabled = False
    
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
        if not self.enabled or not self.client:
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
        
        try:
            # List all objects in the bucket and calculate total size
            total_size = 0
            object_count = 0
            
            paginator = self.client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=self.bucket_name)
            
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        total_size += obj.get('Size', 0)
                        object_count += 1
            
            # Convert bytes to GB
            total_size_gb = total_size / (1024 ** 3)
            
            # Prepare result
            result = {
                'success': True,
                'total_size_bytes': total_size,
                'total_size_gb': round(total_size_gb, 2),
                'object_count': object_count,
                'last_updated': self._get_current_timestamp()
            }
            
            # Cache the result
            cache.set(self.CACHE_KEY, result, self.CACHE_TIMEOUT)
            logger.info(f"R2 storage usage: {total_size_gb:.2f} GB, {object_count} objects")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch R2 bucket usage: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'total_size_bytes': 0,
                'total_size_gb': 0.0,
                'object_count': 0
            }
    
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
