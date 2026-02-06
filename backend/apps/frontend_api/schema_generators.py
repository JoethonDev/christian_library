"""
JSON-LD Schema Generator for SEO
Generates structured data for different content types following Schema.org standards
"""
import json
from django.contrib.sites.models import Site


def _get_absolute_url(path, request=None):
    """
    Internal helper to build absolute URLs consistently across all schema generators.
    Prioritizes request.build_absolute_uri, falls back to Site framework.
    """
    if not path:
        return ""
    if path.startswith('http'):
        return path
    
    if request:
        return request.build_absolute_uri(path)
    
    try:
        current_site = Site.objects.get_current()
        return f"https://{current_site.domain}{path}"
    except:
        return path


def generate_breadcrumb_schema(breadcrumbs, request=None):
    """
    Generate BreadcrumbList structured data for search engine result pages.
    """
    items = []
    for position, (name, url) in enumerate(breadcrumbs, start=1):
        items.append({
            "@type": "ListItem",
            "position": position,
            "name": name,
            "item": _get_absolute_url(url, request)
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items
    }


def generate_video_schema(content_item, request=None, language='en'):
    """
    Generate VideoObject schema for rich video snippets in Google Search.
    Uses optimized SEO metadata and canonical URLs from the model.
    """
    url = content_item.get_canonical_url()
    
    schema = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": content_item.get_seo_title(language),
        "description": content_item.get_seo_meta_description(language),
        "uploadDate": content_item.created_at.isoformat(),
        "url": url,
    }
    
    video_meta = content_item.get_meta_object()
    if video_meta and content_item.content_type == 'video':
        # Re-using direct URL methods from models for accurate content discovery
        schema["contentUrl"] = _get_absolute_url(video_meta.get_best_streaming_url(), request)
        
        # Re-using ISO duration method added to models
        duration_iso = getattr(video_meta, 'get_duration_iso', lambda: None)()
        if duration_iso:
            schema["duration"] = duration_iso
        
        # Safe access to optional thumbnail property
        thumbnail_url = getattr(video_meta, 'thumbnail_url', None)
        if thumbnail_url:
            schema["thumbnailUrl"] = _get_absolute_url(thumbnail_url, request)
    
    # Populate keywords using localized SEO metadata
    keywords_str = content_item.get_seo_keywords(language)
    if keywords_str:
        keywords = [k.strip() for k in keywords_str if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_audio_schema(content_item, request=None, language='en'):
    """
    Generate AudioObject/Podcast schema for audio content.
    """
    url = content_item.get_canonical_url()
    
    schema = {
        "@context": "https://schema.org",
        "@type": "AudioObject",
        "name": content_item.get_seo_title(language),
        "description": content_item.get_seo_meta_description(language),
        "uploadDate": content_item.created_at.isoformat(),
        "url": url,
    }
    
    audio_meta = content_item.get_meta_object()
    if audio_meta and content_item.content_type == 'audio':
        # Use best available playback URL (R2 or local)
        schema["contentUrl"] = _get_absolute_url(audio_meta.get_best_streaming_url(), request)
        
        duration_iso = getattr(audio_meta, 'get_duration_iso', lambda: None)()
        if duration_iso:
            schema["duration"] = duration_iso
            
    keywords_str = content_item.get_seo_keywords(language)
    if keywords_str:
        keywords = [k.strip() for k in keywords_str if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_book_schema(content_item, request=None, language='en'):
    """
    Generate Book schema for PDF content, including page counts and text snippets.
    """
    url = content_item.get_canonical_url()
    
    schema = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": content_item.get_seo_title(language),
        "description": content_item.get_seo_meta_description(language),
        "url": url,
        "datePublished": content_item.created_at.isoformat(),
    }
    
    pdf_meta = content_item.get_meta_object()
    if pdf_meta and content_item.content_type == 'pdf':
        if pdf_meta.page_count:
            schema["numberOfPages"] = pdf_meta.page_count
    
    # Include a sanitized snippet of extracted text for search indexing
    if content_item.book_content:
        snippet = content_item.book_content[:500].strip()
        if snippet:
            schema["text"] = snippet + "..." if len(content_item.book_content) > 500 else snippet
    
    keywords_str = content_item.get_seo_keywords(language)
    if keywords_str:
        keywords = [k.strip() for k in keywords_str if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_creative_work_schema(content_item, request=None, language='en'):
    """
    Fallback generic CreativeWork schema for miscellaneous content types.
    """
    url = content_item.get_canonical_url()
    
    schema = {
        "@context": "https://schema.org",
        "@type": content_item.get_schema_type(),
        "name": content_item.get_seo_title(language),
        "description": content_item.get_seo_meta_description(language),
        "url": url,
        "datePublished": content_item.created_at.isoformat(),
        "dateModified": content_item.updated_at.isoformat(),
    }
    
    keywords_str = content_item.get_seo_keywords(language)
    if keywords_str:
        keywords = [k.strip() for k in keywords_str if k.strip()]
        if keywords:
            schema["keywords"] = ", ".join(keywords[:10])
    
    return schema


def generate_schema_for_content(content_item, request=None, language='en'):
    """
    Universal entry point for generating content-specific structured data.
    Directly leverages model-level schema mapping and metadata accessors.
    """
    ctype = content_item.content_type
    if ctype == 'video':
        return generate_video_schema(content_item, request, language)
    elif ctype == 'audio':
        return generate_audio_schema(content_item, request, language)
    elif ctype == 'pdf':
        return generate_book_schema(content_item, request, language)
    return generate_creative_work_schema(content_item, request, language)


def schema_to_json_ld(schema):
    """
    Convert a schema dictionary into a valid HTML <script> tag for injection.
    """
    return f'<script type="application/ld+json">\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n</script>'
    """
    Convert schema dict to JSON-LD script tag
    
    Args:
        schema: Dictionary containing schema data
    
    Returns:
        HTML script tag with JSON-LD
    """
    json_str = json.dumps(schema, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{json_str}\n</script>'
