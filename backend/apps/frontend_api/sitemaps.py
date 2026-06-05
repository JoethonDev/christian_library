from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings
from apps.media_manager.models import ContentItem


class I18nMixin:
    """Mixin to add i18n alternate language links to sitemap entries"""
    
    def _get_alternate_languages(self, obj_or_url):
        """Generate alternate language links for hreflang support"""
        alternates = []
        for lang_code, lang_name in settings.LANGUAGES:
            # Build alternate URL for each language
            if isinstance(obj_or_url, str):
                # For URL names (home, videos, etc.)
                alternate_url = f'/{lang_code}{reverse(obj_or_url)}'
            else:
                # For ContentItem objects
                alternate_url = f'/{lang_code}{obj_or_url.get_absolute_url()}'
            
            alternates.append({
                'location': alternate_url,
                'lang_code': lang_code,
            })
        return alternates


class HomeSitemap(Sitemap, I18nMixin):
    """Home page sitemap with highest priority - Auto-updated with i18n support"""
    priority = 1.0
    changefreq = 'daily'
    i18n = True
    
    def items(self):
        return ['frontend_api:home']
    
    def location(self, item):
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{reverse(item)}'
    
    def alternates(self, item):
        """Provide alternate language versions"""
        return self._get_alternate_languages(item)
    
    def lastmod(self, item):
        # Cache lastmod for home page based on latest content update
        cache_key = 'sitemap_home_lastmod'
        lastmod = cache.get(cache_key)
        if not lastmod:
            latest_content = ContentItem.objects.filter(is_active=True).order_by('-updated_at').first()
            lastmod = latest_content.updated_at if latest_content else timezone.now()
            cache.set(cache_key, lastmod, 3600)  # Cache for 1 hour
        return lastmod


class ContentListSitemap(Sitemap, I18nMixin):
    """Content listing pages sitemap - Auto-updated based on content changes with i18n"""
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
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{reverse(item)}'
    
    def alternates(self, item):
        """Provide alternate language versions"""
        return self._get_alternate_languages(item)
    
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


class VideoSitemap(Sitemap, I18nMixin):
    """Video content sitemap with SEO optimization and i18n - Auto-updated"""
    priority = 0.8  # High priority for video content
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='video',
            is_active=True
        ).select_related('videometa').order_by('-updated_at')
    
    def location(self, obj):
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{obj.get_absolute_url()}'
    
    def alternates(self, obj):
        """Provide alternate language versions"""
        return self._get_alternate_languages(obj)
    
    def lastmod(self, obj):
        return obj.updated_at
    
    def priority(self, obj):
        """Dynamic priority based on SEO metadata availability"""
        if obj.has_seo_metadata():
            return 0.9  # Higher priority for SEO-optimized content
        return 0.7


class AudioSitemap(Sitemap, I18nMixin):
    """Audio content sitemap with SEO optimization and i18n"""
    priority = 0.7
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='audio',
            is_active=True
        ).select_related('audiometa').order_by('-updated_at')
    
    def location(self, obj):
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{obj.get_absolute_url()}'
    
    def alternates(self, obj):
        """Provide alternate language versions"""
        return self._get_alternate_languages(obj)
    
    def lastmod(self, obj):
        return obj.updated_at
    
    def priority(self, obj):
        """Dynamic priority based on SEO metadata availability"""
        if obj.has_seo_metadata():
            return 0.8  # Higher priority for SEO-optimized content
        return 0.6


class PdfSitemap(Sitemap, I18nMixin):
    """PDF content sitemap with SEO optimization and i18n"""
    priority = 0.6
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='pdf',
            is_active=True
        ).select_related('pdfmeta').order_by('-updated_at')
    
    def location(self, obj):
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{obj.get_absolute_url()}'
    
    def alternates(self, obj):
        """Provide alternate language versions"""
        return self._get_alternate_languages(obj)
    
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


class SEOOptimizedSitemap(Sitemap, I18nMixin):
    """Special sitemap for content with full SEO metadata and i18n"""
    priority = 0.9
    changefreq = 'weekly'
    i18n = True
    
    def items(self):
        """Return only content items with complete SEO metadata"""
        from django.db.models import Q
        return ContentItem.objects.filter(
            is_active=True
        ).exclude(
            Q(seo_keywords_ar='') | Q(seo_keywords_ar__isnull=True) |
            Q(seo_keywords_en='') | Q(seo_keywords_en__isnull=True) |
            Q(seo_meta_description_ar='') | Q(seo_meta_description_ar__isnull=True) |
            Q(seo_meta_description_en='') | Q(seo_meta_description_en__isnull=True)
        ).order_by('-updated_at')
    
    def location(self, obj):
        # Return default language URL
        return f'/{settings.LANGUAGE_CODE}{obj.get_absolute_url()}'
    
    def alternates(self, obj):
        """Provide alternate language versions"""
        return self._get_alternate_languages(obj)
    
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