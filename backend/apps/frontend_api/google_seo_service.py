"""
SEO utility helpers.

Provides sitemap pinging and absolute URL helpers used by content and SEO
signals.
"""
import logging
import requests
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


def get_absolute_content_url(content_item, request=None, language=None):
    """
    Get absolute URL for a content item
    
    Args:
        content_item: ContentItem object
        request: Optional Django request object
        language: Optional language code ('ar' or 'en') to override default
    
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
        
        url_path = content_item.get_absolute_url()
        
        # Override language if specified
        if language:
            if url_path.startswith('/ar/') or url_path.startswith('/en/'):
                url_path = f'/{language}{url_path[3:]}'
            else:
                url_path = f'/{language}{url_path}'
        
        return f"{protocol}://{domain}{url_path}"
    except Exception as e:
        logger.error(f"Error building absolute URL: {e}")
        return content_item.get_absolute_url()

