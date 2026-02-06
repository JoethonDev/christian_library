"""
Analytics utilities for tracking content views.

This module provides utilities for recording anonymous content view events
for videos, audios, PDFs, and static pages.
"""
from django.utils import timezone
from apps.media_manager.models import ContentViewEvent
import logging

logger = logging.getLogger(__name__)


def record_content_view(request, content_type, content_id):
    """
    Record a content view event.
    
    Args:
        request: Django HttpRequest object
        content_type: Type of content ('video', 'audio', 'pdf', 'static')
        content_id: UUID of the content item
        
    Returns:
        ContentViewEvent instance or None if failed
    """
    try:
        # Extract request metadata
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:256]
        ip_address = _get_client_ip(request)
        referrer = request.META.get('HTTP_REFERER', '')[:256]
        
        # Create the view event
        view_event = ContentViewEvent.objects.create(
            content_type=content_type,
            content_id=content_id,
            user_agent=user_agent,
            ip_address=ip_address,
            referrer=referrer,
            timestamp=timezone.now()
        )
        
        logger.debug(f"Recorded view event: {content_type} - {content_id}")
        return view_event
        
    except Exception as e:
        # Don't fail the request if analytics tracking fails
        logger.error(f"Error recording content view: {str(e)}", exc_info=True)
        return None


def _get_client_ip(request):
    """
    Extract the client IP address from the request.
    Handles proxy headers (X-Forwarded-For) and direct connections.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        IP address string or None
    """
    # Check for X-Forwarded-For header (proxy/load balancer)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP in the list (client IP)
        ip = x_forwarded_for.split(',')[0].strip()
        return ip
    
    # Fall back to REMOTE_ADDR
    return request.META.get('REMOTE_ADDR')
