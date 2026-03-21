"""
URL Generator Service
Generates all public URLs that should be indexed by Google:
- Content URLs (videos, audios, PDFs)
- Static pages (home, search, content lists)
- Tag pages
- RSS feeds
"""
import logging
from typing import List, Dict
from django.conf import settings
from django.contrib.sites.models import Site

from apps.media_manager.models import ContentItem, Tag

logger = logging.getLogger(__name__)


class URLGeneratorService:
    """Service for generating all indexable URLs"""
    
    def __init__(self):
        self.base_url = self._get_base_url()
    
    def _get_base_url(self) -> str:
        """Get base URL for the site"""
        try:
            current_site = Site.objects.get_current()
            domain = current_site.domain
            protocol = getattr(
                settings, 
                'SITE_PROTOCOL', 
                'http' if settings.DEBUG or 'localhost' in domain else 'https'
            )
        except Exception as e:
            logger.warning(f"Could not get site domain: {e}")
            domain = getattr(settings, 'SITE_DOMAIN', 'localhost')
            protocol = getattr(settings, 'SITE_PROTOCOL', 'http' if settings.DEBUG else 'https')
        
        return f"{protocol}://{domain}"
    
    def get_content_urls(self, content_type: str = None) -> List[Dict]:
        """
        Get all active content URLs with language variants.
        
        Args:
            content_type: Filter by type ('video', 'audio', 'pdf') or None for all
        
        Returns:
            List of URL dicts with metadata
        """
        queryset = ContentItem.objects.filter(is_active=True)
        
        if content_type and content_type != 'all':
            queryset = queryset.filter(content_type=content_type)
        
        urls = []
        
        for item in queryset.iterator(chunk_size=500):
            for lang in ['ar', 'en']:
                try:
                    url_path = item.get_absolute_url()
                    
                    # Replace language prefix
                    if url_path.startswith('/ar/') or url_path.startswith('/en/'):
                        url_path = f'/{lang}{url_path[3:]}'
                    else:
                        url_path = f'/{lang}{url_path}'
                    
                    absolute_url = f"{self.base_url}{url_path}"
                    
                    urls.append({
                        'url': absolute_url,
                        'url_type': 'content',
                        'content_type': item.content_type,
                        'content_id': str(item.id),
                        'language': lang,
                        # Arabic gets higher priority
                        'priority': 10 if lang == 'ar' else 5
                    })
                except Exception as e:
                    logger.warning(f"Could not build URL for content {item.id}: {e}")
                    continue
        
        logger.info(f"Generated {len(urls)} content URLs")
        return urls
    
    def get_static_page_urls(self) -> List[Dict]:
        """
        Get all static page URLs that should be indexed.
        
        Returns:
            List of static page URLs with metadata
        """
        static_pages = [
            # Home pages
            {'name': 'home', 'path': '/'},
            
            # Search pages
            {'name': 'search', 'path': '/search/'},
            
            # Content list pages
            {'name': 'videos_list', 'path': '/videos/'},
            {'name': 'audios_list', 'path': '/audios/'},
            {'name': 'pdfs_list', 'path': '/pdfs/'},
        ]
        
        urls = []
        
        for page in static_pages:
            for lang in ['ar', 'en']:
                url_path = f'/{lang}{page["path"]}'
                absolute_url = f"{self.base_url}{url_path}"
                
                urls.append({
                    'url': absolute_url,
                    'url_type': 'static_page',
                    'page_name': page['name'],
                    'language': lang,
                    # Static pages medium-high priority
                    'priority': 7
                })
        
        logger.info(f"Generated {len(urls)} static page URLs")
        return urls
    
    def get_tag_urls(self) -> List[Dict]:
        """
        Get all active tag page URLs.
        
        Returns:
            List of tag page URLs
        """
        # Only include tags that have active content
        active_tags = Tag.objects.filter(
            contentitem__is_active=True
        ).distinct()
        
        urls = []
        
        for tag in active_tags:
            for lang in ['ar', 'en']:
                try:
                    # URL pattern: /ar/tags/<uuid>/
                    url_path = f'/{lang}/tags/{tag.id}/'
                    absolute_url = f"{self.base_url}{url_path}"
                    
                    urls.append({
                        'url': absolute_url,
                        'url_type': 'tag_page',
                        'tag_id': str(tag.id),
                        'tag_name': tag.name_ar if lang == 'ar' else tag.name_en,
                        'language': lang,
                        'priority': 6
                    })
                except Exception as e:
                    logger.warning(f"Could not build URL for tag {tag.id}: {e}")
                    continue
        
        logger.info(f"Generated {len(urls)} tag page URLs")
        return urls
    
    def get_feed_urls(self) -> List[Dict]:
        """
        Get RSS feed URLs.
        
        Returns:
            List of RSS feed URLs
        """
        feed_types = ['videos', 'audios', 'pdfs', 'all']
        urls = []
        
        for feed_type in feed_types:
            for lang in ['ar', 'en']:
                # URL pattern: /ar/feed/videos/
                url_path = f'/{lang}/feed/{feed_type}/'
                absolute_url = f"{self.base_url}{url_path}"
                
                urls.append({
                    'url': absolute_url,
                    'url_type': 'rss_feed',
                    'feed_type': feed_type,
                    'language': lang,
                    'priority': 4  # Lower priority for feeds
                })
        
        logger.info(f"Generated {len(urls)} RSS feed URLs")
        return urls
    
    def get_all_urls(self, content_type: str = None, include_static: bool = True) -> List[Dict]:
        """
        Get ALL indexable URLs.
        
        Args:
            content_type: Filter content by type
            include_static: Whether to include static pages, tags, feeds
        
        Returns:
            Complete list of all URLs to index
        """
        all_urls = []
        
        # Always include content URLs
        all_urls.extend(self.get_content_urls(content_type))
        
        if include_static:
            all_urls.extend(self.get_static_page_urls())
            all_urls.extend(self.get_tag_urls())
            all_urls.extend(self.get_feed_urls())
        
        logger.info(f"Generated {len(all_urls)} total URLs for indexing")
        return all_urls
    
    def get_urls_by_priority(self, content_type: str = None, include_static: bool = True) -> Dict[int, List[Dict]]:
        """
        Get all URLs grouped by priority (for sequential submission).
        
        Returns:
            Dict mapping priority -> list of URLs
            Higher priority = submitted first
        """
        all_urls = self.get_all_urls(content_type, include_static)
        
        by_priority = {}
        for url_info in all_urls:
            priority = url_info.get('priority', 5)
            if priority not in by_priority:
                by_priority[priority] = []
            by_priority[priority].append(url_info)
        
        return by_priority


# Singleton instance
_url_generator = None

def get_url_generator() -> URLGeneratorService:
    """Get URL generator service instance"""
    global _url_generator
    if _url_generator is None:
        _url_generator = URLGeneratorService()
    return _url_generator
