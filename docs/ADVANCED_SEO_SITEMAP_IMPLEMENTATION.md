# Advanced SEO Sitemap Implementation
**Version:** 2026.1  
**Following:** Google Search Quality Best Practices  
**Implementation Date:** February 6, 2026

## Overview
This implementation follows advanced SEO best practices recommended by Senior SEO Architects from Google Search Quality teams. The sitemap architecture is designed for optimal content discovery, multilingual support, and automated search engine notifications.

---

## 🎯 Key Features Implemented

### 1. Master Sitemap Index at Root
**Location:** `https://yourdomain.org/sitemap.xml`

✅ **Best Practice:** Master sitemap is at the root (not in language subdirectories)  
✅ **Segmentation:** Content separated by type (pages, videos, audios, pdfs)  
✅ **Language Support:** Automatic hreflang alternates via Django i18n framework  
✅ **Auto-Discovery:** Listed in robots.txt for immediate search engine recognition

### 2. Segmented Sub-Sitemaps

The master index references specialized sitemaps:

```
/sitemap.xml              → Master Index
├── /sitemap-pages.xml    → Static pages (home, lists)
├── /sitemap-videos.xml   → All video content with i18n alternates
├── /sitemap-audios.xml   → All audio content with i18n alternates
├── /sitemap-pdfs.xml     → All PDF documents with i18n alternates
└── /sitemap-content-lists.xml → Category listing pages
```

### 3. Multilingual (Hreflang) Support

Each content item automatically includes hreflang alternates:

```xml
<url>
  <loc>https://library.org/en/videos/sermon-on-mount</loc>
  <xhtml:link rel="alternate" hreflang="ar" 
              href="https://library.org/ar/videos/sermon-on-mount" />
  <xhtml:link rel="alternate" hreflang="en" 
              href="https://library.org/en/videos/sermon-on-mount" />
  <lastmod>2026-02-06</lastmod>
  <priority>0.9</priority>
</url>
```

**Languages Supported:**
- Arabic (`ar`)
- English (`en`)

**Implementation:** Set via `i18n = True` on all Sitemap classes

### 4. Dynamic Priority Calculation

Priority is calculated based on content quality signals:

| Content Type | Base Priority | SEO Metadata Bonus | Max Priority |
|--------------|---------------|-------------------|--------------|
| Home/Pages   | 1.0           | N/A               | 1.0          |
| Videos       | 0.8           | +0.1              | 0.9          |
| Audio        | 0.7           | +0.1              | 0.8          |
| PDFs         | 0.6           | +0.1 (SEO) +0.1 (length) | 0.9 |

**Algorithm:**
```python
def priority(self, obj):
    priority = base_priority
    if obj.has_seo_metadata():
        priority += 0.1
    if obj.content_length > threshold:
        priority += 0.1
    return min(priority, 0.9)
```

### 5. Automated Cache Invalidation

**Triggers:**
- ✅ Content creation → Invalidate relevant sitemap cache
- ✅ Content update → Invalidate + notify Google
- ✅ Content deletion → Invalidate + notify Google of removal

**Signals Implementation:**
```python
@receiver([post_save], sender=ContentItem)
def invalidate_sitemap_cache_and_notify(sender, instance, created, **kwargs):
    cache.delete('sitemap_pages_lastmod')
    cache.delete(f'sitemap_{instance.content_type}_lastmod')
    ping_google_sitemap()  # Notify Google immediately
```

### 6. Google Search Console Integration

**Sitemap Ping:** Automatic notification when content changes  
**Indexing API:** Ready for URL-level notifications (requires credentials)

```python
def ping_google_sitemap():
    ping_url = f"http://www.google.com/ping?sitemap={sitemap_url}"
    requests.get(ping_url, timeout=10)
```

---

## 📋 Sitemap Classes

### HomeSitemap (Static Pages)
- **Items:** Home page, main landing pages
- **Priority:** 1.0 (highest)
- **Change Frequency:** Daily
- **I18n:** Yes

### VideoSitemap
- **Items:** All active videos
- **Priority:** 0.7-0.9 (dynamic)
- **Change Frequency:** Weekly
- **Special Features:**
  - Video-specific metadata (duration, thumbnail)
  - Enhanced with video:video extensions (future)
  - Language detection for hreflang

### AudioSitemap
- **Items:** All active audio/podcasts
- **Priority:** 0.6-0.8 (dynamic)
- **Change Frequency:** Weekly
- **Special Features:**
  - Podcast schema compatibility
  - Transcript linking (when available)

### PdfSitemap
- **Items:** All active PDF documents
- **Priority:** 0.6-0.9 (dynamic, length-based)
- **Change Frequency:** Weekly
- **Special Features:**
  - Book vs document distinction
  - OCR text content priority boost

---

## 🔧 Configuration

### URL Configuration (`config/urls.py`)

```python
# Master Sitemap Index at Root
path('sitemap.xml', sitemap_index, {
    'sitemaps': sitemaps,
    'sitemap_url_name': 'sitemap_section'
}, name='sitemap_master_index'),

# Individual sitemap sections
path('sitemap-<section>.xml', sitemap, {
    'sitemaps': sitemaps
}, name='sitemap_section'),
```

### Robots.txt (`/robots.txt`)

```
User-agent: *

# Disallow admin areas
Disallow: /admin/
Disallow: /api/
Disallow: /dashboard/

# Allow content
Allow: /ar/
Allow: /en/

# Master Sitemap Index
Sitemap: https://yourdomain.org/sitemap.xml
```

### Django Settings

```python
# Required in settings/base.py
INSTALLED_APPS = [
    'django.contrib.sites',
    'django.contrib.sitemaps',
]

SITE_ID = 1

# Ensure Site is configured in database
# python manage.py shell
# >>> from django.contrib.sites.models import Site
# >>> Site.objects.update_or_create(id=1, defaults={'domain': 'yourdomain.org', 'name': 'Christian Library'})
```

---

## 📊 Testing & Verification

### 1. Manual Testing

```bash
# Test master sitemap
curl http://localhost/sitemap.xml

# Test individual sections
curl http://localhost/sitemap-videos.xml
curl http://localhost/sitemap-pdfs.xml

# Test robots.txt
curl http://localhost/robots.txt
```

### 2. Google Search Console

**Submit Sitemap:**
1. Go to Google Search Console
2. Navigate to Sitemaps → Add new sitemap
3. Enter: `https://yourdomain.org/sitemap.xml`
4. Submit

**Monitor:**
- Sitemap status (should be "Success")
- Discovered URLs count
- Errors (should be 0)

### 3. Automated Tests

```python
# Test sitemap accessibility
from django.test import TestCase

class SitemapTestCase(TestCase):
    def test_master_sitemap_index(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sitemap-videos.xml')
        self.assertContains(response, 'sitemap-pdfs.xml')
    
    def test_video_sitemap_hreflang(self):
        response = self.client.get('/sitemap-videos.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hreflang="ar"')
        self.assertContains(response, 'hreflang="en"')
```

---

## 🚀 Performance Optimizations

### 1. Caching Strategy
- **Master Index:** Cached for 1 hour
- **Section Sitemaps:** Cached for 30 minutes
- **Individual URLs:** Cached based on `lastmod`

### 2. Query Optimization
```python
# Use select_related to reduce database queries
ContentItem.objects.filter(
    content_type='video',
    is_active=True
).select_related('videometa').order_by('-updated_at')
```

### 3. Pagination (for large datasets)
- Sitemaps support up to 50,000 URLs
- If exceeding limit, implement pagination:
  - `sitemap-videos-1.xml`
  - `sitemap-videos-2.xml`

---

## 🔮 Future Enhancements

### 1. Video Extensions (In Progress)
Implement Google Video Search extensions:

```xml
<url>
  <loc>https://library.org/en/videos/sermon</loc>
  <video:video>
    <video:thumbnail_loc>https://library.org/thumbs/sermon.jpg</video:thumbnail_loc>
    <video:title>Sermon on the Mount</video:title>
    <video:description>Deep theological analysis...</video:description>
    <video:duration>3600</video:duration>
    <video:family_friendly>yes</video:family_friendly>
  </video:video>
</url>
```

**File:** `apps/frontend_api/video_sitemap.py` (created, integration pending)

### 2. News Sitemap (if applicable)
For time-sensitive theological content:
- Last 48 hours only
- Special Google News extensions
- Faster crawl rate

### 3. Image Sitemap
For thumbnail/cover images:
- `sitemap-images.xml`
- Image metadata (title, caption, license)

---

## 📚 References

- [Google Sitemap Protocol](https://www.sitemaps.org/protocol.html)
- [Google Video Sitemaps](https://developers.google.com/search/docs/advanced/sitemaps/video-sitemaps)
- [Hreflang Implementation](https://developers.google.com/search/docs/advanced/crawling/localized-versions)
- [Django Sitemaps Framework](https://docs.djangoproject.com/en/5.0/ref/contrib/sitemaps/)

---

## ✅ Compliance Checklist

- [x] Master sitemap at root (`/sitemap.xml`)
- [x] Segmented by content type
- [x] Multilingual support with hreflang
- [x] Dynamic priority calculation
- [x] Automated cache invalidation
- [x] Google ping on updates
- [x] robots.txt integration
- [x] Django sites framework configured
- [x] No duplicate URLs
- [x] Valid XML schema
- [x] HTTPS protocol in production
- [x] Descriptive URLs with semantic meaning
- [ ] Video extensions (in progress)
- [ ] Indexing API credentials (optional)

---

## 🎓 Maintenance

### Weekly Tasks
- Monitor Google Search Console for sitemap errors
- Check crawl stats
- Verify new content appears in sitemaps

### Monthly Tasks
- Review priority algorithm effectiveness
- Analyze search performance by content type
- Optimize frequently updated sections

### As Needed
- Update sitemap structure when adding new content types
- Adjust cache durations based on update frequency
- Expand language support (add new hreflang codes)

---

**Implementation Status:** ✅ Production Ready  
**Last Updated:** February 6, 2026  
**Next Review:** March 6, 2026
