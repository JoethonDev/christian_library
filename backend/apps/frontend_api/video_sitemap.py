"""
Video Sitemap with Google Video Extensions
Following SEO best practices for video content discovery
"""
from django.contrib.sitemaps import Sitemap
from django.template.loader import render_to_string
from django.utils.html import escape
from apps.media_manager.models import ContentItem
from django.contrib.sites.models import Site


class VideoSitemapWithExtensions(Sitemap):
    """
    Enhanced Video Sitemap with Google Video Search Extensions
    Implements video:video tags for better video discoverability
    """
    priority = 0.8
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
        """Dynamic priority based on SEO metadata"""
        if obj.has_seo_metadata():
            return 0.9
        return 0.7
    
    def get_video_data(self, obj):
        """
        Extract video-specific metadata for sitemap extensions
        Returns dict with video metadata following Google's schema
        """
        try:
            current_site = Site.objects.get_current()
            domain = current_site.domain
            protocol = 'https'
        except:
            domain = 'localhost'
            protocol = 'http'
        
        video_data = {
            'title': obj.get_title('en') or obj.get_title('ar') or 'Untitled Video',
            'description': obj.get_description('en') or obj.get_description('ar') or '',
            'upload_date': obj.created_at.isoformat(),
        }
        
        # Add video-specific metadata if available
        if hasattr(obj, 'videometa') and obj.videometa:
            videometa = obj.videometa
            
            # Thumbnail
            if videometa.thumbnail:
                video_data['thumbnail_loc'] = f"{protocol}://{domain}{videometa.thumbnail.url}"
            
            # Duration (in seconds)
            if videometa.duration:
                video_data['duration'] = int(videometa.duration)
            
            # Content location (video file URL)
            if videometa.file_url:
                video_data['content_loc'] = videometa.file_url
            elif obj.storage_path:
                video_data['content_loc'] = f"{protocol}://{domain}/media/{obj.storage_path}"
        
        # Add category from tags
        if obj.tags.exists():
            video_data['category'] = obj.tags.first().name
        
        # Add family-friendly flag (default to yes for religious content)
        video_data['family_friendly'] = 'yes'
        
        return video_data
    
    def get_languages_for_item(self, obj):
        """Return available languages for this video"""
        languages = []
        if obj.title_ar or obj.description_ar:
            languages.append('ar')
        if obj.title_en or obj.description_en:
            languages.append('en')
        return languages if languages else ['ar', 'en']
