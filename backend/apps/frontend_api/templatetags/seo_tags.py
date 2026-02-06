"""
Template tags for SEO features
Provides easy access to schema generation and SEO metadata in templates
"""
from django import template
from django.utils.safestring import mark_safe
from apps.frontend_api.schema_generators import (
    generate_schema_for_content,
    generate_breadcrumb_schema,
    schema_to_json_ld
)
import json

register = template.Library()


@register.simple_tag(takes_context=True)
def content_schema(context, content_item):
    """
    Generate JSON-LD schema for a content item
    
    Usage in template:
        {% load seo_tags %}
        {% content_schema content_item %}
    """
    request = context.get('request')
    schema = generate_schema_for_content(content_item, request)
    return mark_safe(schema_to_json_ld(schema))


@register.simple_tag(takes_context=True)
def breadcrumb_schema(context, breadcrumbs):
    """
    Generate JSON-LD breadcrumb schema
    
    Usage in template:
        {% load seo_tags %}
        {% breadcrumb_schema breadcrumbs %}
    
    Where breadcrumbs is a list of tuples: [('Home', '/'), ('Videos', '/videos/')]
    """
    request = context.get('request')
    schema = generate_breadcrumb_schema(breadcrumbs, request)
    return mark_safe(schema_to_json_ld(schema))


@register.filter
def seo_meta_description(content_item, language='en'):
    """
    Get SEO meta description for a content item with fallback
    
    Usage in template:
        {% load seo_tags %}
        {{ content_item|seo_meta_description:"ar" }}
    """
    return content_item.get_seo_meta_description(language)


@register.filter
def seo_keywords(content_item, language='en'):
    """
    Get SEO keywords as a list
    
    Usage in template:
        {% load seo_tags %}
        {{ content_item|seo_keywords:"ar" }}
    """
    return content_item.get_seo_keywords(language)


@register.filter
def seo_keywords_string(content_item, language='en'):
    """
    Get SEO keywords as a comma-separated string
    
    Usage in template:
        {% load seo_tags %}
        <meta name="keywords" content="{{ content_item|seo_keywords_string:'en' }}">
    """
    keywords = content_item.get_seo_keywords(language)
    return ', '.join(keywords) if keywords else ''


@register.simple_tag
def organization_schema(organization_name="Christian Library", domain="example.com"):
    """
    Generate JSON-LD organization schema
    
    Usage in template:
        {% load seo_tags %}
        {% organization_schema "Christian Library" "library.org" %}
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": organization_name,
        "url": f"https://{domain}",
        "logo": f"https://{domain}/static/images/logo.png",
        "sameAs": [
            # Add social media profiles here
        ]
    }
    return mark_safe(schema_to_json_ld(schema))


@register.simple_tag(takes_context=True)
def website_schema(context):
    """
    Generate JSON-LD website schema
    
    Usage in template:
        {% load seo_tags %}
        {% website_schema %}
    """
    request = context.get('request')
    domain = request.get_host() if request else 'example.com'
    protocol = 'https' if (request and request.is_secure()) else 'https'
    
    schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Christian Library",
        "url": f"{protocol}://{domain}",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{protocol}://{domain}/ar/search/?q={{search_term_string}}"
            },
            "query-input": "required name=search_term_string"
        }
    }
    return mark_safe(schema_to_json_ld(schema))


@register.inclusion_tag('seo/meta_tags.html', takes_context=True)
def seo_meta_tags(context, content_item, language='ar'):
    """
    Include comprehensive SEO meta tags
    
    Usage in template:
        {% load seo_tags %}
        {% seo_meta_tags content_item "ar" %}
    """
    request = context.get('request')
    
    # Get absolute URL
    if request:
        protocol = 'https' if request.is_secure() else 'http'
        domain = request.get_host()
        absolute_url = f"{protocol}://{domain}{content_item.get_absolute_url()}"
    else:
        absolute_url = content_item.get_absolute_url()
    
    return {
        'content_item': content_item,
        'language': language,
        'absolute_url': absolute_url,
        'title': content_item.get_title(language),
        'description': content_item.get_seo_meta_description(language),
        'keywords': seo_keywords_string(content_item, language),
        'image_url': getattr(content_item.get_meta_object(), 'thumbnail_url', None) if content_item.get_meta_object() else None,
    }
