from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.media_manager.models import ContentItem


class HomeSitemap(Sitemap):
    """Home page sitemap with highest priority"""
    priority = 1.0
    changefreq = 'daily'
    
    def items(self):
        return ['frontend_api:home']
    
    def location(self, item):
        return reverse(item)


class ContentListSitemap(Sitemap):
    """Content listing pages sitemap"""
    priority = 0.8
    changefreq = 'daily'
    
    def items(self):
        return [
            'frontend_api:videos',
            'frontend_api:audios', 
            'frontend_api:pdfs'
        ]
    
    def location(self, item):
        return reverse(item)


class VideoSitemap(Sitemap):
    """Video content sitemap with SEO optimization"""
    priority = 0.8  # High priority for video content
    changefreq = 'weekly'
    
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


class SEOOptimizedSitemap(Sitemap):
    """Special sitemap for content with full SEO metadata"""
    priority = 0.9
    changefreq = 'weekly'
    
    def items(self):
        """Return only content items with complete SEO metadata"""
        return ContentItem.objects.filter(
            is_active=True,
            seo_keywords_ar__len__gt=0,
            seo_keywords_en__len__gt=0,
        ).exclude(
            seo_meta_description_ar='',
            seo_meta_description_en=''
        ).order_by('-updated_at')
    
    def location(self, obj):
        return obj.get_absolute_url()
    
    def lastmod(self, obj):
        return obj.updated_at


# Legacy sitemaps for backward compatibility
class PdfListSitemap(ContentListSitemap):
    """Legacy PDF list sitemap - redirects to ContentListSitemap"""
    def items(self):
        return ['frontend_api:pdfs']


class PdfDetailSitemap(PdfSitemap):
    """Legacy PDF detail sitemap - redirects to PdfSitemap"""
    pass