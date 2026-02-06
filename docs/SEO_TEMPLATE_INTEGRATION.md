# SEO Template Integration Guide

## Overview
This guide shows how to integrate SEO features (meta tags, JSON-LD schemas, Open Graph tags) into your Django templates for the Christian Library application.

## Using SEO Template Tags

### 1. Load the Template Tags
At the top of your template, load the SEO tags:

```django
{% load seo_tags %}
```

### 2. Add Schema to Content Detail Pages

The schema is now automatically added to the context in the views (`video_detail`, `audio_detail`, `pdf_detail`), so you can simply include it in your template's head section:

```django
{# In video_detail.html, audio_detail.html, or pdf_detail.html #}
<!DOCTYPE html>
<html>
<head>
    {# ... other head tags ... #}
    
    {# SEO Meta Tags #}
    {% load seo_tags %}
    {% seo_meta_tags video 'ar' %}
    
    {# JSON-LD Schema (auto-generated and passed from view) #}
    {{ schema_json_ld|safe }}
</head>
<body>
    {# ... page content ... #}
</body>
</html>
```

### 3. Alternative: Using Template Tags Directly

If you prefer to generate schema directly in templates:

```django
{% load seo_tags %}

<!DOCTYPE html>
<html>
<head>
    {# Method 1: Generate schema using template tag #}
    {% content_schema video %}
    
    {# Method 2: Include meta tags #}
    {% seo_meta_tags video 'ar' %}
</head>
<body>
    {# ... content ... #}
</body>
</html>
```

### 4. Add Breadcrumb Navigation with Schema

```django
{% load seo_tags %}

{# Define breadcrumbs #}
{% with breadcrumbs=breadcrumb_list %}
    {% breadcrumb_schema breadcrumbs %}
{% endwith %}

{# Example breadcrumb list for video detail page #}
{# In your view, add to context: #}
{# breadcrumb_list = [ #}
{#     ('الرئيسية', '/ar/'),  #}
{#     ('الفيديوهات', '/ar/videos/'),  #}
{#     (video.get_title('ar'), '') #}
{# ] #}
```

### 5. Using Individual Filters

For custom implementations:

```django
{% load seo_tags %}

{# Get meta description #}
<meta name="description" content="{{ content_item|seo_meta_description:'ar' }}">

{# Get keywords as comma-separated string #}
<meta name="keywords" content="{{ content_item|seo_keywords_string:'en' }}">

{# Get keywords as list (for iteration) #}
{% for keyword in content_item|seo_keywords:'ar' %}
    <span class="keyword">{{ keyword }}</span>
{% endfor %}
```

## Complete Example: Video Detail Page

```django
{% extends "base.html" %}
{% load seo_tags %}
{% load i18n %}

{% block title %}{{ video.get_title }}{% endblock %}

{% block extra_head %}
    {# SEO Meta Tags (includes Open Graph and Twitter Card) #}
    {% seo_meta_tags video 'ar' %}
    
    {# JSON-LD Schema (VideoObject) #}
    {{ schema_json_ld|safe }}
    
    {# Website Search Schema #}
    {% website_schema %}
{% endblock %}

{% block content %}
<main>
    {# Breadcrumb Navigation #}
    <nav aria-label="breadcrumb">
        <ol class="breadcrumb">
            <li class="breadcrumb-item"><a href="/">{% trans "Home" %}</a></li>
            <li class="breadcrumb-item"><a href="{% url 'frontend_api:videos' %}">{% trans "Videos" %}</a></li>
            <li class="breadcrumb-item active">{{ video.get_title }}</li>
        </ol>
    </nav>
    
    {# Video Player #}
    <div class="video-container">
        {# ... video player code ... #}
    </div>
    
    {# Video Information #}
    <div class="video-info">
        <h1>{{ video.get_title }}</h1>
        <p>{{ video.get_description }}</p>
        
        {# Tags #}
        <div class="tags">
            {% for tag in video.tags.all %}
                <a href="{% url 'frontend_api:tag_content' tag.id %}" class="badge badge-primary">
                    {{ tag.get_name }}
                </a>
            {% endfor %}
        </div>
    </div>
    
    {# Related Videos #}
    <div class="related-videos">
        <h2>{% trans "Related Videos" %}</h2>
        {# ... related videos grid ... #}
    </div>
</main>
{% endblock %}
```

## Available Template Tags

### Simple Tags

1. **`{% content_schema content_item %}`**
   - Generates appropriate schema based on content type
   - Returns: Complete JSON-LD script tag

2. **`{% breadcrumb_schema breadcrumbs %}`**
   - Generates BreadcrumbList schema
   - Input: List of tuples `[('Name', 'URL'), ...]`
   - Returns: JSON-LD script tag

3. **`{% organization_schema "Org Name" "domain.com" %}`**
   - Generates Organization schema
   - Returns: JSON-LD script tag

4. **`{% website_schema %}`**
   - Generates WebSite schema with search action
   - Returns: JSON-LD script tag

### Inclusion Tags

1. **`{% seo_meta_tags content_item language %}`**
   - Includes complete SEO meta tags template
   - Includes: description, keywords, Open Graph, Twitter Card
   - Language: 'ar' or 'en'

### Filters

1. **`{{ content_item|seo_meta_description:'ar' }}`**
   - Returns: Meta description string

2. **`{{ content_item|seo_keywords:'ar' }}`**
   - Returns: List of keywords

3. **`{{ content_item|seo_keywords_string:'ar' }}`**
   - Returns: Comma-separated keywords string

## Best Practices

### 1. Always Include Basic SEO
Every page should have at minimum:
- Title tag
- Meta description
- Meta keywords (for Arabic content especially)
- Open Graph tags

### 2. Schema Placement
Place JSON-LD schemas in the `<head>` section:
```django
<head>
    {# Standard meta tags #}
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    
    {# SEO meta tags #}
    {% seo_meta_tags content 'ar' %}
    
    {# JSON-LD schemas #}
    {{ schema_json_ld|safe }}
</head>
```

### 3. Language Consistency
Use the same language throughout:
```django
{# If page is in Arabic #}
{% seo_meta_tags video 'ar' %}
{% breadcrumb_schema ar_breadcrumbs %}

{# If page is in English #}
{% seo_meta_tags video 'en' %}
{% breadcrumb_schema en_breadcrumbs %}
```

### 4. Breadcrumbs
Always include breadcrumb navigation with schema:
```django
{% load seo_tags %}

{# Define breadcrumbs in view or template #}
{% breadcrumb_schema breadcrumb_list %}

{# Also show visible breadcrumbs #}
<nav aria-label="breadcrumb">
    <ol class="breadcrumb">
        {% for name, url in breadcrumb_list %}
            <li class="breadcrumb-item{% if forloop.last %} active{% endif %}">
                {% if url %}<a href="{{ url }}">{{ name }}</a>{% else %}{{ name }}{% endif %}
            </li>
        {% endfor %}
    </ol>
</nav>
```

### 5. Validate Your Schemas
After implementation:
1. Use [Google Rich Results Test](https://search.google.com/test/rich-results)
2. Enter your page URL
3. Check for errors or warnings
4. Fix any issues

## Troubleshooting

### Schema Not Appearing
1. Check that `{% load seo_tags %}` is at the top of your template
2. Verify the context variable name matches (e.g., `video`, `audio`, `pdf`)
3. Check that `|safe` filter is used when outputting HTML

### Meta Tags Not Showing
1. Verify SEO metadata exists on the content item
2. Check that content has required fields (title, description)
3. Ensure the inclusion tag template exists at `templates/seo/meta_tags.html`

### Breadcrumb Schema Invalid
1. Ensure breadcrumbs is a list of tuples: `[('Name', 'URL'), ...]`
2. Check that URLs are either absolute or start with `/`
3. Verify the last breadcrumb can have an empty URL

## Updates and Maintenance

### When Content is Updated
Schemas are automatically regenerated on each page load. No caching of schemas is done to ensure they're always fresh.

### When Adding New Content Types
1. Add schema generator in `schema_generators.py`
2. Update `generate_schema_for_content()` function
3. Update view to pass schema to template
4. Test with Rich Results tool

## Additional Resources

- [Schema.org Documentation](https://schema.org/)
- [Google Search Central](https://developers.google.com/search)
- [Open Graph Protocol](https://ogp.me/)
- [Twitter Card Documentation](https://developer.twitter.com/en/docs/twitter-for-websites/cards)
