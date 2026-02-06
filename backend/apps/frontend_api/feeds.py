"""
RSS/Atom Feeds for Christian Library
Auto-updated feeds for latest content additions
"""
from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Atom1Feed
from django.urls import reverse
from django.utils import timezone
from apps.media_manager.models import ContentItem
from django.contrib.sites.models import Site


class LatestContentFeed(Feed):
    """RSS feed for latest content across all types"""
    title = "Christian Library - Latest Content"
    description = "Latest videos, audios, and PDFs added to the Christian Library"
    
    def link(self):
        return reverse('frontend_api:home')
    
    def items(self):
        """Return latest 50 active content items"""
        return ContentItem.objects.filter(
            is_active=True
        ).select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).order_by('-created_at')[:50]
    
    def item_title(self, item):
        """Return item title in Arabic (primary language)"""
        return item.get_title('ar')
    
    def item_description(self, item):
        """Return item description in Arabic"""
        description = item.get_description('ar')
        # Limit description length for feed
        if len(description) > 500:
            return description[:497] + "..."
        return description
    
    def item_link(self, item):
        """Return absolute URL for the item"""
        try:
            current_site = Site.objects.get_current()
            return f"https://{current_site.domain}{item.get_absolute_url()}"
        except:
            return item.get_absolute_url()
    
    def item_pubdate(self, item):
        """Return publication date"""
        return item.created_at
    
    def item_updateddate(self, item):
        """Return last update date"""
        return item.updated_at
    
    def item_categories(self, item):
        """Return tags as categories"""
        return [tag.get_name('ar') for tag in item.tags.all()[:5]]
    
    def item_author_name(self, item):
        """Return author if available"""
        return "Christian Library"


class LatestVideosFeed(Feed):
    """RSS feed for latest video content"""
    title = "Christian Library - Latest Videos"
    description = "Latest video content added to the Christian Library"
    
    def link(self):
        return reverse('frontend_api:videos')
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='video',
            is_active=True
        ).select_related('videometa').order_by('-created_at')[:30]
    
    def item_title(self, item):
        return item.get_title('ar')
    
    def item_description(self, item):
        description = item.get_description('ar')
        if len(description) > 500:
            return description[:497] + "..."
        return description
    
    def item_link(self, item):
        try:
            current_site = Site.objects.get_current()
            return f"https://{current_site.domain}{item.get_absolute_url()}"
        except:
            return item.get_absolute_url()
    
    def item_pubdate(self, item):
        return item.created_at
    
    def item_updateddate(self, item):
        return item.updated_at


class LatestAudiosFeed(Feed):
    """RSS feed for latest audio content"""
    title = "Christian Library - Latest Audios"
    description = "Latest audio content added to the Christian Library"
    
    def link(self):
        return reverse('frontend_api:audios')
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='audio',
            is_active=True
        ).select_related('audiometa').order_by('-created_at')[:30]
    
    def item_title(self, item):
        return item.get_title('ar')
    
    def item_description(self, item):
        description = item.get_description('ar')
        if len(description) > 500:
            return description[:497] + "..."
        return description
    
    def item_link(self, item):
        try:
            current_site = Site.objects.get_current()
            return f"https://{current_site.domain}{item.get_absolute_url()}"
        except:
            return item.get_absolute_url()
    
    def item_pubdate(self, item):
        return item.created_at
    
    def item_updateddate(self, item):
        return item.updated_at


class LatestPdfsFeed(Feed):
    """RSS feed for latest PDF content"""
    title = "Christian Library - Latest PDFs"
    description = "Latest PDF books and documents added to the Christian Library"
    
    def link(self):
        return reverse('frontend_api:pdfs')
    
    def items(self):
        return ContentItem.objects.filter(
            content_type='pdf',
            is_active=True
        ).select_related('pdfmeta').order_by('-created_at')[:30]
    
    def item_title(self, item):
        return item.get_title('ar')
    
    def item_description(self, item):
        description = item.get_description('ar')
        if len(description) > 500:
            return description[:497] + "..."
        return description
    
    def item_link(self, item):
        try:
            current_site = Site.objects.get_current()
            return f"https://{current_site.domain}{item.get_absolute_url()}"
        except:
            return item.get_absolute_url()
    
    def item_pubdate(self, item):
        return item.created_at
    
    def item_updateddate(self, item):
        return item.updated_at


class LatestContentAtomFeed(LatestContentFeed):
    """Atom feed version of latest content"""
    feed_type = Atom1Feed
    subtitle = LatestContentFeed.description
