# Content Viewing Analytics & Admin Analytics Page: Implementation Plan

This plan details the steps to implement anonymous content viewing analytics for videos, audios, PDFs, and static pages, along with an admin dashboard for analytics visualization. The approach is tailored to the Christian Library project structure and leverages Django models, admin views, and templates.

---

## Objectives

1. **Track anonymous views for all content types (video, audio, PDF, static pages).**
2. **Store analytics data efficiently for reporting and visualization.**
3. **Provide an admin analytics dashboard with charts and tables.**
4. **Expose endpoints for analytics data retrieval.**

---

## 1. Models: Analytics Data Storage

### a. ContentViewEvent Model
```python
from django.db import models
from django.utils import timezone

class ContentViewEvent(models.Model):
    CONTENT_TYPE_CHOICES = [
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('pdf', 'PDF'),
        ('static', 'Static Page'),
    ]
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPE_CHOICES, db_index=True)
    content_id = models.UUIDField(db_index=True)  # UUID for ContentItem or static page slug
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user_agent = models.CharField(max_length=256, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    referrer = models.CharField(max_length=256, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_type', 'content_id', 'timestamp']),
        ]
        verbose_name = 'Content View Event'
        verbose_name_plural = 'Content View Events'
```

### b. DailyContentViewSummary Model (for aggregation)
```python
class DailyContentViewSummary(models.Model):
    content_type = models.CharField(max_length=10, choices=ContentViewEvent.CONTENT_TYPE_CHOICES, db_index=True)
    content_id = models.UUIDField(db_index=True)
    date = models.DateField(db_index=True)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('content_type', 'content_id', 'date')
        indexes = [
            models.Index(fields=['content_type', 'content_id', 'date']),
        ]
        verbose_name = 'Daily Content View Summary'
        verbose_name_plural = 'Daily Content View Summaries'
```

---

## 2. Analytics Collection Logic

- **Middleware or View Decorator:**
  - Add a decorator or middleware to increment a view event each time a content detail page (video, audio, PDF, static) is accessed.
  - Example usage in a view:
    ```python
    from apps.media_manager.models import ContentViewEvent
    def record_content_view(request, content_type, content_id):
        ContentViewEvent.objects.create(
            content_type=content_type,
            content_id=content_id,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:256],
            ip_address=request.META.get('REMOTE_ADDR'),
            referrer=request.META.get('HTTP_REFERER', '')[:256],
        )
    ```
  - Call `record_content_view` in each content detail view (e.g., `video_detail`, `audio_detail`, `pdf_detail`, static page views).

- **Aggregation Task:**
  - Nightly Celery task to aggregate `ContentViewEvent` into `DailyContentViewSummary` for efficient reporting.

---

## 3. Admin Analytics Dashboard

### a. Admin View (admin_views.py)
```python
from django.shortcuts import render
from apps.media_manager.models import DailyContentViewSummary, ContentItem
from django.db.models import Sum
from datetime import timedelta, date

def analytics_dashboard(request):
    # Date range (last 30 days)
    end_date = date.today()
    start_date = end_date - timedelta(days=29)

    # Aggregate views by content type and date
    summaries = DailyContentViewSummary.objects.filter(date__range=(start_date, end_date))
    stats = summaries.values('content_type', 'date').annotate(total_views=Sum('view_count')).order_by('date')

    # Top content by views
    top_content = summaries.values('content_type', 'content_id').annotate(total_views=Sum('view_count')).order_by('-total_views')[:20]

    # Optionally join with ContentItem for titles
    content_map = {c.id: c for c in ContentItem.objects.filter(id__in=[x['content_id'] for x in top_content])}
    for item in top_content:
        item['title'] = content_map.get(item['content_id']).title_ar if item['content_id'] in content_map else 'Unknown'

    context = {
        'stats': stats,
        'top_content': top_content,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'admin/analytics_dashboard.html', context)
```

### b. URL Registration (urls.py)
```python
path('dashboard/analytics/', admin_views.analytics_dashboard, name='analytics_dashboard'),
```

### c. Template (admin/analytics_dashboard.html)
- Use Bootstrap 5 and Chart.js for charts.
- Show:
  - Line chart: Daily views per content type (last 30 days)
  - Table: Top 20 most viewed content items (title, type, total views)
  - Filters for date range and content type

---

## 4. API Endpoints for Analytics Data

- Add endpoints to provide JSON data for charts (e.g., `/api/analytics/views/`), returning aggregated stats for frontend chart rendering.
- Example:
  ```python
  from django.http import JsonResponse
  def api_analytics_views(request):
      # ...aggregate as above...
      return JsonResponse({'stats': list(stats)})
  ```

---

## 5. Testing

- Unit tests for event recording, aggregation, and dashboard queries.
- Integration tests for analytics endpoints and dashboard rendering.

---

## 6. Deliverables

- New models: `ContentViewEvent`, `DailyContentViewSummary`
- Analytics collection logic in content detail views
- Celery aggregation task
- Admin analytics dashboard view and template
- API endpoints for analytics data
- Documentation and tests

---

## Timeline
| Task                        | Estimated Time |
|-----------------------------|----------------|
| Models & Migration          | 1 day          |
| Analytics Collection Logic  | 1 day          |
| Aggregation Task            | 1 day          |
| Admin Dashboard View        | 2 days         |
| Templates & Charts          | 2 days         |
| API Endpoints               | 1 day          |
| Testing                     | 1 day          |
| **Total**                   | **9 days**     |

---

This plan provides a clear, project-specific roadmap for implementing content viewing analytics and an admin analytics dashboard in the Christian Library project.