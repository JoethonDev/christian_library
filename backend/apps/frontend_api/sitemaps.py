from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.core.cache import cache
from django.utils import timezone
from django.contrib.sites.models import Site
from apps.media_manager.models import ContentItem


class HomeSitemap(Sitemap):
    """Home page sitemap with highest priority - Auto-updated"""
    priority = 1.0
    changefreq = 'daily'
    i18n = True
    
    def items(self):
        return ['frontend_api:home']
    
    def location(self, item):
        return reverse(item)
    
    def lastmod(self, item):
        # Cache lastmod for home page based on latest content update
        cache_key = 'sitemap_home_lastmod'
        lastmod = cache.get(cache_key)
        if not lastmod:
            latest_content = ContentItem.objects.filter(is_active=True).order_by('-updated_at').first()
            lastmod = latest_content.updated_at if latest_content else timezone.now()
            cache.set(cache_key, lastmod, 3600)  # Cache for 1 hour
        return lastmod


class ContentListSitemap(Sitemap):
    """Content listing pages sitemap - Auto-updated based on content changes"""
    priority = 0.8
    changefreq = 'daily'
    i18n = True
    
    def items(self):
        return [
            'frontend_api:videos',
            'frontend_api:audios', 
            'frontend_api:pdfs'
        ]
    
    def location(self, item):
        return reverse(item)
    
    def lastmod(self, item):
        # Get content type from URL name
        content_type = item.split(':')[1].rstrip('s')  # videos -> video, audios -> audio, pdfs -> pdf
        if content_type == 'pdf':
            content_type = 'pdf'  # Handle edge case
        
        cache_key = f'sitemap_{content_type}_lastmod'
        lastmod = cache.get(cache_key)
        if not lastmod:
            latest_content = ContentItem.objects.filter(
                content_type=content_type, 
                is_active=True
            ).order_by('-updated_at').first()
            lastmod = latest_content.updated_at if latest_content else timezone.now()
            cache.set(cache_key, lastmod, 1800)  # Cache for 30 minutes
        return lastmod


class VideoSitemap(Sitemap):
    """Video content sitemap with SEO optimization - Auto-updated"""
    priority = 0.8  # High priority for video content
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='video',
            is_active=True
        ).select_related('videometa').order_by('-updated_at')
    
    def location(self, obj):
        return obj.get_absolute_url()
    
    def lastmod(self, obj):
        return obj.updated_at
    
    def priority(self, obj):
        """Dynamic priority based on SEO metadata availability"""
        if obj.has_seo_metadata():
            return 0.9  # Higher priority for SEO-optimized content
        return 0.7


class AudioSitemap(Sitemap):
    """Audio content sitemap with SEO optimization"""
    priority = 0.7
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='audio',
            is_active=True
        ).select_related('audiometa').order_by('-updated_at')
    
    def location(self, obj):
        return obj.get_absolute_url()
    
    def lastmod(self, obj):
        return obj.updated_at
    
    def priority(self, obj):
        """Dynamic priority based on SEO metadata availability"""
        if obj.has_seo_metadata():
            return 0.8  # Higher priority for SEO-optimized content
        return 0.6


class PdfSitemap(Sitemap):
    """PDF content sitemap with SEO optimization"""
    priority = 0.6
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='pdf',
            is_active=True
        ).select_related('pdfmeta').order_by('-updated_at')
    
    def location(self, obj):
        return obj.get_absolute_url()
    
    def lastmod(self, obj):
        return obj.updated_at
    
    def priority(self, obj):
        """Dynamic priority based on SEO metadata and content length"""
        priority = 0.6
        
        # Higher priority for SEO-optimized content
        if obj.has_seo_metadata():
            priority += 0.1
        
        # Higher priority for longer content (books vs short documents)
        if hasattr(obj, 'book_content') and obj.book_content:
            content_length = len(obj.book_content)
            if content_length > 10000:  # Long content (books)
                priority += 0.1
            elif content_length > 1000:  # Medium content
                priority += 0.05
        
        return min(priority, 0.9)  # Cap at 0.9


# Legacy sitemaps for backward compatibility
class PdfListSitemap(ContentListSitemap):
    """Legacy PDF list sitemap - redirects to ContentListSitemap"""
    def items(self):
        return ['frontend_api:pdfs']


class PdfDetailSitemap(PdfSitemap):
    """Legacy PDF detail sitemap - redirects to PdfSitemap"""
    pass