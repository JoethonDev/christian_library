"""
Google SEO Services
- Sitemap ping to notify Google of updates
- Google Indexing API integration for URL updates
"""
import logging
import requests
from django.conf import settings
from django.contrib.sites.models import Site
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def ping_google_sitemap(request=None):
    """
    Ping Google to notify of sitemap updates
    
    Args:
        request: Optional Django request object to get domain
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the sitemap URL
        if request:
            protocol = 'https' if request.is_secure() else 'http'
            domain = request.get_host()
        else:
            try:
                current_site = Site.objects.get_current()
                domain = current_site.domain
                protocol = 'https'  # Always use HTTPS for production
            except:
                logger.warning("Could not determine site domain for sitemap ping")
                return False
        
        sitemap_url = f"{protocol}://{domain}/sitemap.xml"
        
        # Build the ping URL
        ping_url = f"http://www.google.com/ping?{urlencode({'sitemap': sitemap_url})}"
        
        # Send the ping (with timeout)
        response = requests.get(ping_url, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Successfully pinged Google with sitemap: {sitemap_url}")
            return True
        else:
            logger.warning(f"Google sitemap ping returned status {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error pinging Google sitemap: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error pinging Google sitemap: {e}")
        return False


def notify_google_indexing_api(url, action='URL_UPDATED'):
    """
    Notify Google Indexing API about URL changes
    
    Note: Requires Google API credentials to be configured
    This is a placeholder implementation. To use:
    1. Set up Google Cloud project
    2. Enable Indexing API
    3. Create service account and download JSON key
    4. Set GOOGLE_SERVICE_ACCOUNT_FILE in settings
    5. Install google-auth and google-api-python-client
    
    Args:
        url: Absolute URL to notify Google about
        action: 'URL_UPDATED' or 'URL_DELETED'
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Check if API is configured
    service_account_file = getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_FILE', None)
    
    if not service_account_file:
        logger.debug("Google Indexing API not configured (GOOGLE_SERVICE_ACCOUNT_FILE not set)")
        return False
    
    try:
        # Import Google API libraries (only if configured)
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        # Load credentials
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=['https://www.googleapis.com/auth/indexing']
        )
        
        # Build the service
        service = build('indexing', 'v3', credentials=credentials)
        
        # Prepare the request body
        body = {
            'url': url,
            'type': action
        }
        
        # Send the notification
        response = service.urlNotifications().publish(body=body).execute()
        
        logger.info(f"Successfully notified Google Indexing API: {url} ({action})")
        return True
        
    except ImportError:
        logger.warning("Google API libraries not installed. Install: pip install google-auth google-api-python-client")
        return False
    except Exception as e:
        logger.error(f"Error notifying Google Indexing API: {e}")
        return False


def get_absolute_content_url(content_item, request=None):
    """
    Get absolute URL for a content item
    
    Args:
        content_item: ContentItem object
        request: Optional Django request object
    
    Returns:
        str: Absolute URL
    """
    try:
        if request:
            protocol = 'https' if request.is_secure() else 'http'
            domain = request.get_host()
        else:
            current_site = Site.objects.get_current()
            domain = current_site.domain
            protocol = 'https'
        
        return f"{protocol}://{domain}{content_item.get_absolute_url()}"
    except Exception as e:
        logger.error(f"Error building absolute URL: {e}")
        return content_item.get_absolute_url()


def notify_content_update(content_item, request=None):
    """
    Notify Google of content update via Indexing API
    
    Args:
        content_item: ContentItem object that was created or updated
        request: Optional Django request object
    
    Returns:
        bool: True if successful, False otherwise
    """
    url = get_absolute_content_url(content_item, request)
    return notify_google_indexing_api(url, action='URL_UPDATED')


def notify_content_deletion(content_item, request=None):
    """
    Notify Google of content deletion via Indexing API
    
    Args:
        content_item: ContentItem object that was deleted
        request: Optional Django request object
    
    Returns:
        bool: True if successful, False otherwise
    """
    url = get_absolute_content_url(content_item, request)
    return notify_google_indexing_api(url, action='URL_DELETED')
