"""
JSON-LD Schema Generator for SEO
Generates structured data for different content types following Schema.org standards
"""
import json
from datetime import datetime
from django.contrib.sites.models import Site
from django.urls import reverse


def generate_breadcrumb_schema(breadcrumbs, request=None):
    """
    Generate BreadcrumbList schema
    
    Args:
        breadcrumbs: List of tuples (name, url)
        request: Django request object for building absolute URLs
    
    Returns:
        JSON-LD formatted breadcrumb schema
    """
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
        protocol = 'https' if (request and request.is_secure()) else 'https'
    except:
        domain = request.get_host() if request else 'example.com'
        protocol = 'https'
    
    items = []
    for position, (name, url) in enumerate(breadcrumbs, start=1):
        # Make URL absolute if it's relative
        if url.startswith('/'):
            url = f"{protocol}://{domain}{url}"
        
        items.append({
            "@type": "ListItem",
            "position": position,
            "name": name,
            "item": url
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items
    }


def generate_video_schema(content_item, request=None):
    """
    Generate VideoObject schema for video content
    
    Args:
        content_item: ContentItem object with content_type='video'
        request: Django request object
    
    Returns:
        JSON-LD formatted VideoObject schema
    """
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
        protocol = 'https' if (request and request.is_secure()) else 'https'
    except:
        domain = request.get_host() if request else 'example.com'
        protocol = 'https'
    
    url = f"{protocol}://{domain}{content_item.get_absolute_url()}"
    
    schema = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": content_item.get_title('en') or content_item.get_title('ar'),
        "description": content_item.get_description('en') or content_item.get_description('ar'),
        "uploadDate": content_item.created_at.isoformat(),
        "contentUrl": url,
    }
    
    # Add optional fields if available
    if hasattr(content_item, 'videometa') and content_item.videometa:
        video_meta = content_item.videometa
        
        if video_meta.duration:
            # Convert duration to ISO 8601 duration format (PT#H#M#S)
            hours = int(video_meta.duration // 3600)
            minutes = int((video_meta.duration % 3600) // 60)
            seconds = int(video_meta.duration % 60)
            duration_str = f"PT{hours}H{minutes}M{seconds}S" if hours else f"PT{minutes}M{seconds}S"
            schema["duration"] = duration_str
        
        if video_meta.thumbnail_url:
            schema["thumbnailUrl"] = video_meta.thumbnail_url
    
    # Add keywords from SEO metadata
    if content_item.seo_keywords_en:
        keywords = [k.strip() for k in content_item.seo_keywords_en.split(',') if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])  # Limit to 10 keywords
    
    return schema


def generate_audio_schema(content_item, request=None):
    """
    Generate AudioObject/Podcast schema for audio content
    
    Args:
        content_item: ContentItem object with content_type='audio'
        request: Django request object
    
    Returns:
        JSON-LD formatted AudioObject schema
    """
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
        protocol = 'https' if (request and request.is_secure()) else 'https'
    except:
        domain = request.get_host() if request else 'example.com'
        protocol = 'https'
    
    url = f"{protocol}://{domain}{content_item.get_absolute_url()}"
    
    schema = {
        "@context": "https://schema.org",
        "@type": "AudioObject",
        "name": content_item.get_title('en') or content_item.get_title('ar'),
        "description": content_item.get_description('en') or content_item.get_description('ar'),
        "uploadDate": content_item.created_at.isoformat(),
        "contentUrl": url,
    }
    
    # Add optional fields if available
    if hasattr(content_item, 'audiometa') and content_item.audiometa:
        audio_meta = content_item.audiometa
        
        if audio_meta.duration:
            # Convert duration to ISO 8601 duration format
            hours = int(audio_meta.duration // 3600)
            minutes = int((audio_meta.duration % 3600) // 60)
            seconds = int(audio_meta.duration % 60)
            duration_str = f"PT{hours}H{minutes}M{seconds}S" if hours else f"PT{minutes}M{seconds}S"
            schema["duration"] = duration_str
    
    # Add keywords from SEO metadata
    if content_item.seo_keywords_en:
        keywords = [k.strip() for k in content_item.seo_keywords_en.split(',') if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_book_schema(content_item, request=None):
    """
    Generate Book schema for PDF content
    
    Args:
        content_item: ContentItem object with content_type='pdf'
        request: Django request object
    
    Returns:
        JSON-LD formatted Book schema
    """
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
        protocol = 'https' if (request and request.is_secure()) else 'https'
    except:
        domain = request.get_host() if request else 'example.com'
        protocol = 'https'
    
    url = f"{protocol}://{domain}{content_item.get_absolute_url()}"
    
    schema = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": content_item.get_title('en') or content_item.get_title('ar'),
        "description": content_item.get_description('en') or content_item.get_description('ar'),
        "url": url,
        "datePublished": content_item.created_at.isoformat(),
    }
    
    # Add optional fields if available
    if hasattr(content_item, 'pdfmeta') and content_item.pdfmeta:
        pdf_meta = content_item.pdfmeta
        
        if pdf_meta.page_count:
            schema["numberOfPages"] = pdf_meta.page_count
    
    # Add text content if available (for searchability)
    if content_item.book_content:
        # Include a snippet of the content (first 500 characters)
        snippet = content_item.book_content[:500].strip()
        if snippet:
            schema["text"] = snippet + "..." if len(content_item.book_content) > 500 else snippet
    
    # Add keywords from SEO metadata
    if content_item.seo_keywords_en:
        keywords = [k.strip() for k in content_item.seo_keywords_en.split(',') if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_creative_work_schema(content_item, request=None):
    """
    Generate generic CreativeWork schema for any content type
    Fallback schema when specific type is not applicable
    
    Args:
        content_item: ContentItem object
        request: Django request object
    
    Returns:
        JSON-LD formatted CreativeWork schema
    """
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
        protocol = 'https' if (request and request.is_secure()) else 'https'
    except:
        domain = request.get_host() if request else 'example.com'
        protocol = 'https'
    
    url = f"{protocol}://{domain}{content_item.get_absolute_url()}"
    
    schema = {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        "name": content_item.get_title('en') or content_item.get_title('ar'),
        "description": content_item.get_description('en') or content_item.get_description('ar'),
        "url": url,
        "datePublished": content_item.created_at.isoformat(),
        "dateModified": content_item.updated_at.isoformat(),
    }
    
    # Add keywords from SEO metadata
    if content_item.seo_keywords_en:
        keywords = [k.strip() for k in content_item.seo_keywords_en.split(',') if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_schema_for_content(content_item, request=None):
    """
    Generate appropriate schema based on content type
    
    Args:
        content_item: ContentItem object
        request: Django request object
    
    Returns:
        JSON-LD formatted schema appropriate for content type
    """
    if content_item.content_type == 'video':
        return generate_video_schema(content_item, request)
    elif content_item.content_type == 'audio':
        return generate_audio_schema(content_item, request)
    elif content_item.content_type == 'pdf':
        return generate_book_schema(content_item, request)
    else:
        return generate_creative_work_schema(content_item, request)


def schema_to_json_ld(schema):
    """
    Convert schema dict to JSON-LD script tag
    
    Args:
        schema: Dictionary containing schema data
    
    Returns:
        HTML script tag with JSON-LD
    """
    json_str = json.dumps(schema, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{json_str}\n</script>'
