# SEO Configuration and Setup Guide

## Overview

This Christian Library application includes comprehensive SEO features to ensure optimal indexing by search engines, particularly Google. This document covers the setup, configuration, and troubleshooting of all SEO-related features.

## Features

### 1. Dynamic robots.txt
- **URL**: `/robots.txt`
- **Description**: Automatically generated robots.txt that:
  - Disallows crawling of admin areas, API endpoints, and dashboards
  - Allows all public content pages (videos, audios, PDFs)
  - Includes sitemap reference
  - Updates automatically based on site configuration

### 2. XML Sitemaps
- **Main Sitemap Index**: `/sitemap.xml`
- **Individual Sections**:
  - `/sitemap-home.xml` - Home page
  - `/sitemap-content-lists.xml` - Content listing pages
  - `/sitemap-videos.xml` - All video content
  - `/sitemap-audios.xml` - All audio content
  - `/sitemap-pdfs.xml` - All PDF content
  - `/sitemap-seo-optimized.xml` - Content with complete SEO metadata

**Features**:
- Auto-updates when content is created, updated, or deleted
- Includes lastmod timestamps for each URL
- Uses Django's sitemap framework for standard compliance
- Cached for performance with automatic cache invalidation

### 3. RSS/Atom Feeds
- **Latest Content (RSS)**: `/feeds/latest.rss`
- **Latest Content (Atom)**: `/feeds/latest.atom`
- **Videos Feed**: `/feeds/videos.rss`
- **Audios Feed**: `/feeds/audios.rss`
- **PDFs Feed**: `/feeds/pdfs.rss`

**Features**:
- Updates instantly when new content is added
- Includes item metadata (title, description, categories, publish date)
- Supports both RSS 2.0 and Atom 1.0 formats
- Limited to 50 latest items for main feed, 30 for specific content types

### 4. JSON-LD Structured Data
Schema markup for rich search results:
- **VideoObject** - Video content with duration, thumbnails, upload dates
- **AudioObject** - Audio content with duration and metadata
- **Book** - PDF content with page counts and text snippets
- **CreativeWork** - Generic fallback schema
- **BreadcrumbList** - Navigation breadcrumbs

### 5. Google Integration

#### Google Sitemap Ping
Automatically notifies Google when sitemaps are updated:
- Triggered on every content create/update/delete
- Sends HTTP request to `http://www.google.com/ping?sitemap=https://yourdomain.com/sitemap.xml`
- Non-blocking (doesn't slow down content operations)

#### Google Indexing API
Notifies Google of specific URL updates for faster indexing:
- Requires Google Cloud project setup (see below)
- Sends `URL_UPDATED` notification on content creation/update
- Sends `URL_DELETED` notification on content deletion
- Optional - application works without it

## Setup Instructions

### Basic Setup (Required)

1. **Configure Django Sites Framework**
   ```python
   # In Django admin or shell
   from django.contrib.sites.models import Site
   site = Site.objects.get_current()
   site.domain = 'yourlibrary.org'  # Your actual domain
   site.name = 'Christian Library'
   site.save()
   ```

2. **Verify URLs are accessible**
   - Visit `/robots.txt` - Should show robots.txt content
   - Visit `/sitemap.xml` - Should show sitemap index
   - Visit `/feeds/latest.rss` - Should show RSS feed

3. **Submit to Google Search Console**
   - Add your site to [Google Search Console](https://search.google.com/search-console)
   - Submit sitemap URL: `https://yourlibrary.org/sitemap.xml`
   - Monitor indexing status

### Advanced Setup (Optional)

#### Google Indexing API Configuration

1. **Create Google Cloud Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing

2. **Enable Indexing API**
   - In the project, go to APIs & Services → Library
   - Search for "Indexing API"
   - Click "Enable"

3. **Create Service Account**
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "Service Account"
   - Fill in details and create
   - Grant "Owner" role to the service account

4. **Download JSON Key**
   - In the service account details, click "Keys"
   - Add Key → Create New Key → JSON
   - Download the JSON file

5. **Configure Application**
   ```python
   # In settings.py or environment variables
   GOOGLE_SERVICE_ACCOUNT_FILE = '/path/to/service-account-key.json'
   ```

6. **Install Google API Libraries**
   ```bash
   pip install google-auth google-api-python-client
   ```

7. **Verify in Search Console**
   - Add the service account email to Search Console as an owner
   - Service account email format: `service-account-name@project-id.iam.gserviceaccount.com`

## Monitoring and Maintenance

### SEO Dashboard
Access the SEO dashboard at `/ar/dashboard/seo/` or `/en/dashboard/seo/` (requires admin login)

**Metrics Available**:
- Total content count
- SEO coverage percentage
- Content with complete SEO metadata
- Recent SEO updates
- Top keywords analysis
- Content type breakdown

### Manual Operations

#### Force Sitemap Update
```python
# In Django shell
from django.core.cache import cache
cache.delete('sitemap_home_lastmod')
cache.delete('sitemap_video_lastmod')
cache.delete('sitemap_audio_lastmod')
cache.delete('sitemap_pdf_lastmod')
cache.delete('sitemap_cache')
```

#### Manual Google Ping
```python
# In Django shell
from apps.frontend_api.google_seo_service import ping_google_sitemap
ping_google_sitemap()
```

#### Manual Indexing API Notification
```python
# In Django shell
from apps.frontend_api.google_seo_service import notify_content_update
from apps.media_manager.models import ContentItem

content = ContentItem.objects.get(id='your-content-id')
notify_content_update(content)
```

## Troubleshooting

### Sitemap Not Updating
1. Check that signals are connected:
   ```python
   # In Django shell
   from django.db.models.signals import post_save
   from apps.media_manager.models import ContentItem
   print(post_save.receivers)  # Should include sitemap signal
   ```

2. Clear cache manually (see above)

3. Check logs for errors:
   ```bash
   # Check Django logs
   tail -f /path/to/logs/django.log | grep sitemap
   ```

### Google Not Receiving Pings
1. Verify domain is correctly configured in Sites framework
2. Check network connectivity from server
3. Review logs for ping errors:
   ```bash
   tail -f /path/to/logs/django.log | grep "ping Google"
   ```

### Indexing API Not Working
1. Verify `GOOGLE_SERVICE_ACCOUNT_FILE` is set correctly
2. Check that service account has proper permissions
3. Verify service account email is added to Search Console
4. Check logs for API errors:
   ```bash
   tail -f /path/to/logs/django.log | grep "Indexing API"
   ```

### RSS Feed Shows No Content
1. Verify content exists and is marked as active:
   ```python
   from apps.media_manager.models import ContentItem
   ContentItem.objects.filter(is_active=True).count()
   ```

2. Check feed URL is correct
3. Verify content has required fields (title, description)

## Best Practices

### Content Requirements for SEO
Every content item should have:
1. **Unique title** - Both Arabic and English
2. **Meta description** - 150-160 characters, descriptive
3. **Keywords** - 5-10 relevant keywords
4. **Transcript/Summary** - At least 300 words for videos/audios
5. **Alt text for thumbnails** - Descriptive text for images

### URL Structure
- URLs are automatically generated as: `/ar/videos/{uuid}/`, `/ar/audios/{uuid}/`, `/ar/pdfs/{uuid}/`
- UUIDs ensure uniqueness
- Language prefix helps with internationalization

### Schema Markup Validation
Test your structured data:
1. Visit [Google Rich Results Test](https://search.google.com/test/rich-results)
2. Enter a content URL
3. Verify schema is detected and valid
4. Fix any errors reported

### Regular Maintenance
1. **Weekly**: Review SEO dashboard for coverage gaps
2. **Monthly**: Check Google Search Console for indexing issues
3. **After major updates**: Manually ping Google sitemap
4. **Quarterly**: Audit and update keywords and meta descriptions

## API Reference

### Schema Generators
```python
from apps.frontend_api.schema_generators import (
    generate_video_schema,
    generate_audio_schema,
    generate_book_schema,
    generate_schema_for_content,
    schema_to_json_ld
)

# Generate schema for a content item
content = ContentItem.objects.get(id='...')
schema = generate_schema_for_content(content, request)

# Convert to JSON-LD for templates
json_ld = schema_to_json_ld(schema)
```

### Google Services
```python
from apps.frontend_api.google_seo_service import (
    ping_google_sitemap,
    notify_content_update,
    notify_content_deletion,
    get_absolute_content_url
)

# Ping Google sitemap
ping_google_sitemap(request)

# Notify about content update
notify_content_update(content_item, request)

# Notify about deletion
notify_content_deletion(content_item, request)
```

## Support and Resources

- **Django Sitemaps Documentation**: https://docs.djangoproject.com/en/stable/ref/contrib/sitemaps/
- **Django Syndication Framework**: https://docs.djangoproject.com/en/stable/ref/contrib/syndication/
- **Google Search Central**: https://developers.google.com/search
- **Google Indexing API**: https://developers.google.com/search/apis/indexing-api/v3/quickstart
- **Schema.org Documentation**: https://schema.org/docs/schemas.html

## Changelog

### Version 1.0 (Current)
- Initial SEO implementation
- Dynamic robots.txt with sitemap reference
- Multi-section XML sitemaps with auto-update
- RSS/Atom feeds for all content types
- JSON-LD structured data generators
- Google sitemap ping integration
- Google Indexing API integration
- Comprehensive test coverage
- SEO dashboard with analytics
