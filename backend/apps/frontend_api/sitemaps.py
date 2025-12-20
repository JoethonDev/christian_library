from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.media_manager.models import ContentItem

class HomeSitemap(Sitemap):
    priority = 1.0
    changefreq = 'daily'
    def items(self):
        return ['frontend_api:home']
    def location(self, item):
        return reverse(item)

class PdfListSitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'
    def items(self):
        return ['frontend_api:pdfs']
    def location(self, item):
        return reverse(item)

class PdfDetailSitemap(Sitemap):
    priority = 0.7
    changefreq = 'weekly'
    def items(self):
        return ContentItem.objects.filter(content_type='pdf', is_active=True)
    def location(self, obj):
        return obj.get_absolute_url()