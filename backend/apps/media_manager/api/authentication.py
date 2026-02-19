"""
Simple API Secret Key Authentication for RESTful upload API.
Uses X-API-Secret-Key header for authentication.
"""
import hashlib
import logging
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework import authentication
from rest_framework import exceptions

logger = logging.getLogger(__name__)
User = get_user_model()


class APISecretKeyAuthentication(authentication.BaseAuthentication):
    """
    Simple header-based authentication using X-API-Secret-Key.
    
    Rate limiting: 100 requests/hour per API key (Redis-based).
    Returns a system user for API requests.
    """
    
    def authenticate(self, request):
        """
        Authenticate the request using X-API-Secret-Key header.
        
        Returns:
            Tuple[User, None]: System user and None (no auth token)
        
        Raises:
            AuthenticationFailed: If key is missing, invalid, or rate limit exceeded
        """
        api_key = request.META.get('HTTP_X_API_SECRET_KEY')
        
        if not api_key:
            # Allow other authentication methods to try
            return None
        
        # Validate against configured secret key
        configured_key = getattr(settings, 'API_SECRET_KEY', None)
        
        if not configured_key:
            logger.error("API_SECRET_KEY not configured in settings")
            raise exceptions.AuthenticationFailed('API authentication not configured')
        
        if api_key != configured_key:
            logger.warning(f"Invalid API key attempt from {self._get_client_ip(request)}")
            raise exceptions.AuthenticationFailed('Invalid API key')
        
        # Check rate limit
        if not self._check_rate_limit(api_key, request):
            logger.warning(f"Rate limit exceeded for API key from {self._get_client_ip(request)}")
            raise exceptions.Throttled(detail='Rate limit exceeded (100 requests/hour)')
        
        # Log successful authentication
        self._log_access(request, api_key, success=True)
        
        # Return a system user for API requests
        # We use get_or_create to handle the system user
        user, created = User.objects.get_or_create(
            username='api_system',
            defaults={
                'email': 'api@system.local',
                'is_staff': False,
                'is_superuser': False,
            }
        )
        
        return (user, None)
    
    def authenticate_header(self, request):
        """
        Return the WWW-Authenticate header value.
        """
        return 'X-API-Secret-Key'
    
    def _check_rate_limit(self, api_key, request):
        """
        Check if request is within rate limit (100 requests/hour).
        Uses Redis for tracking.
        
        Returns:
            bool: True if within limit, False otherwise
        """
        # Create a hash of the API key for cache key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cache_key = f'api_rate_limit:{key_hash}'
        
        # Get current count
        try:
            current_count = cache.get(cache_key, 0)
            
            # Rate limit: 100 requests per hour
            if current_count >= 100:
                return False
            
            # Increment count (expire after 1 hour)
            cache.set(cache_key, current_count + 1, timeout=3600)
            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            # On cache error, allow the request (fail open)
            return True
    
    def _get_client_ip(self, request):
        """Get client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def _log_access(self, request, api_key, success=True):
        """Log API access attempt."""
        try:
            from apps.media_manager.models import APIUploadLog
            
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            APIUploadLog.objects.create(
                api_key_hash=key_hash,
                endpoint=request.path,
                method=request.method,
                status_code=200 if success else 401,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        except Exception as e:
            logger.error(f"Error logging API access: {e}")
