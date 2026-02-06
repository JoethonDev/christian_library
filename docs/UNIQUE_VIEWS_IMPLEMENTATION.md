# Analytics Improvements Summary - Unique Views and Chart Fixes

## Overview
This document describes the improvements made to the analytics system to differentiate between total views and unique views, and to fix chart rendering issues.

## Problem Statement

Two issues needed to be addressed:

1. **No distinction between total and unique views**: The system only tracked total view counts without identifying unique visitors based on IP addresses
2. **Charts not working**: Analytics graphs were not rendering properly due to date serialization issues

## Solutions Implemented

### 1. Unique Views Tracking

#### Database Model Update
Added `unique_view_count` field to `DailyContentViewSummary` model:

```python
class DailyContentViewSummary(models.Model):
    # ... existing fields ...
    view_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('View Count'),
        help_text=_('Total number of views')
    )
    unique_view_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Unique View Count'),
        help_text=_('Number of unique views based on IP address')
    )
```

**Migration**: `0013_add_unique_view_count.py`

#### Aggregation Task Update
Updated `aggregate_daily_content_views()` task to count unique IPs:

```python
# Count total views
total_views = event_data['count']

# Count unique views (distinct IP addresses)
unique_views = ContentViewEvent.objects.filter(
    timestamp__gte=start_datetime,
    timestamp__lte=end_datetime,
    content_type=event_data['content_type'],
    content_id=event_data['content_id']
).values('ip_address').distinct().count()

# Update summary with both counts
summary, created = DailyContentViewSummary.objects.update_or_create(
    content_type=event_data['content_type'],
    content_id=event_data['content_id'],
    date=yesterday,
    defaults={
        'view_count': total_views,
        'unique_view_count': unique_views
    }
)
```

#### Dashboard Views Update
Updated `analytics_dashboard()` view to calculate and display unique views:

**Historical Data**:
```python
for stat in summaries.values('content_type', 'date').annotate(
    total_views=Sum('view_count'),
    unique_views=Sum('unique_view_count')  # NEW
):
    daily_stats_list.append({
        'content_type': stat['content_type'],
        'date': stat['date'].isoformat(),
        'total_views': stat['total_views'],
        'unique_views': stat['unique_views']  # NEW
    })
```

**Real-time Data (Today)**:
```python
# Calculate unique views for today (distinct IPs per content type)
today_unique_stats = {}
for content_type in ['video', 'audio', 'pdf', 'static']:
    unique_count = today_events.filter(
        content_type=content_type
    ).values('ip_address').distinct().count()
    if unique_count > 0:
        today_unique_stats[content_type] = unique_count
```

**Top Content**:
```python
# Count unique IPs for this content today
unique_today = today_events.filter(
    content_type=item['content_type'],
    content_id=item['content_id']
).values('ip_address').distinct().count()
```

### 2. Chart Rendering Fix

#### Problem
Python `date` objects were being serialized into the template context, but JavaScript couldn't properly parse them. This caused:
- Charts not rendering
- Date sorting issues
- JavaScript errors

#### Solution
Convert dates to ISO format strings **before** template rendering:

**Before** (broken):
```python
daily_stats_list.append({
    'content_type': stat['content_type'],
    'date': end_date,  # Python date object
    'total_views': stat['total_views']
})
```

**After** (fixed):
```python
daily_stats_list.append({
    'content_type': stat['content_type'],
    'date': end_date.isoformat(),  # ISO string: "2026-02-06"
    'total_views': stat['total_views'],
    'unique_views': stat['unique_views']
})
```

#### JavaScript Compatibility
Now JavaScript can properly:
```javascript
const dates = [...new Set(dailyStats.map(s => s.date))].sort();
// Works correctly with ISO date strings
```

### 3. Dashboard UI Updates

#### Summary Cards
Updated to show 4 cards:
1. **Total Views**: All view counts combined
2. **Unique Visitors**: NEW - Distinct IP addresses
3. **Items Viewed**: Content items with views
4. **Top Content Type**: Most viewed category with unique count

```html
<!-- Unique Views Card -->
<div class="col-12 col-md-6 col-xl-3">
    <div class="card border-0 shadow-sm rounded-4 h-100">
        <div class="card-body">
            <div class="bg-success bg-opacity-10 text-success rounded-3 p-2">
                <i class="bi bi-person-check fs-4"></i>
            </div>
            <h2>{{ total_unique_views|default:"0"|floatformat:0 }}</h2>
            <p>{% trans "Unique Visitors" %}</p>
        </div>
    </div>
</div>
```

#### Top Content Table
Added "Unique Views" column:

| # | Title | Type | Total Views | Unique Views |
|---|-------|------|-------------|--------------|
| 1 | Video Title | Video | 1,234 | 567 |
| 2 | Audio Title | Audio | 890 | 345 |

```html
<th>{% trans "Total Views" %}</th>
<th>{% trans "Unique Views" %}</th>
```

## Data Flow

### View Event → Aggregation → Dashboard

```
User visits content page
    ↓
AJAX tracks view with IP address
    ↓
ContentViewEvent created (with ip_address)
    ↓
Nightly aggregation task runs
    ↓
Counts total views: COUNT(*)
Counts unique views: COUNT(DISTINCT ip_address)
    ↓
DailyContentViewSummary updated
    ↓
Dashboard displays both metrics
```

## Metrics Displayed

### Dashboard Shows:
1. **Total Views**: Sum of all view_count
2. **Unique Visitors**: Sum of all unique_view_count
3. **Daily Stats**: Both total and unique views per day/type
4. **Top Content**: Both total and unique views per item
5. **Type Breakdown**: Both metrics per content type

### Example Data:
```
Video: 1,234 total views, 567 unique visitors
- Same user viewing 3 times = 3 total views, 1 unique view
- 100 users each viewing once = 100 total, 100 unique
- 50 users each viewing twice = 100 total, 50 unique
```

## Database Schema

### ContentViewEvent (unchanged)
```sql
id              BIGSERIAL
content_type    VARCHAR(10)
content_id      UUID
timestamp       TIMESTAMP
user_agent      VARCHAR(256)
ip_address      INET           -- Used for unique counting
referrer        VARCHAR(256)
```

### DailyContentViewSummary (updated)
```sql
id                  BIGSERIAL
content_type        VARCHAR(10)
content_id          UUID
date                DATE
view_count          INTEGER        -- Total views
unique_view_count   INTEGER        -- NEW: Unique IPs
```

## Performance Considerations

### Unique View Counting
- Uses `DISTINCT ip_address` which is efficient with proper indexing
- Calculated during nightly aggregation (not real-time)
- For today's data: Real-time calculation (acceptable for current day only)

### Database Queries
```python
# Historical data: Single query with aggregation
summaries.values('content_type', 'date').annotate(
    total_views=Sum('view_count'),
    unique_views=Sum('unique_view_count')
)

# Today's unique views: One query per content type (4 queries max)
today_events.filter(content_type='video').values('ip_address').distinct().count()
```

## Migration Guide

### Applying Migration
```bash
cd backend
python manage.py migrate media_manager 0013
```

### Backfilling Data
If you have existing DailyContentViewSummary records without unique counts, you can backfill:

```python
from apps.media_manager.models import ContentViewEvent, DailyContentViewSummary
from django.db.models import Count

# For each summary without unique_view_count
for summary in DailyContentViewSummary.objects.filter(unique_view_count=0):
    # Count unique IPs for that day
    unique_count = ContentViewEvent.objects.filter(
        content_type=summary.content_type,
        content_id=summary.content_id,
        timestamp__date=summary.date
    ).values('ip_address').distinct().count()
    
    summary.unique_view_count = unique_count
    summary.save()
```

**Note**: Only works if ContentViewEvent data still exists (before 90-day cleanup)

## Testing

### Manual Testing
1. Visit content pages from different IPs
2. Visit same content multiple times from one IP
3. Wait for aggregation task or run manually
4. Check dashboard shows:
   - Total views = all visits
   - Unique views = distinct IPs

### Verification Queries
```python
# Check today's data
from apps.media_manager.models import ContentViewEvent
from django.utils import timezone

today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
events = ContentViewEvent.objects.filter(timestamp__gte=today_start)

print(f"Total events: {events.count()}")
print(f"Unique IPs: {events.values('ip_address').distinct().count()}")
```

## Privacy Considerations

### IP Address Storage
- IP addresses are stored for analytics purposes
- Used only for counting unique visitors
- Not displayed to end users
- Auto-deleted after 90 days (existing cleanup task)

### GDPR Compliance
- IP addresses are personal data under GDPR
- Stored for legitimate interest (analytics)
- Limited retention period (90 days)
- No cross-site tracking
- Anonymous (not linked to user accounts)

## Future Enhancements

### Potential Improvements
1. **Geographic Analytics**: Parse IPs for country/region (with user consent)
2. **Device Analytics**: Parse user agents for device types
3. **Retention Metrics**: Track returning vs new visitors
4. **Session Tracking**: Group views into sessions
5. **Real-time Dashboard**: WebSocket updates for live stats

## Troubleshooting

### Charts Not Rendering
1. Check browser console for JavaScript errors
2. Verify `daily_stats` is array of objects with string dates
3. Confirm Chart.js library is loaded
4. Check that `dailyStats.length > 0` condition is met

### Unique Views = 0
1. Verify ContentViewEvent records have IP addresses
2. Check aggregation task ran successfully
3. For today's data, ensure real-time calculation is working
4. Verify database query returns distinct IPs

### Migration Errors
1. Ensure previous migration (0012) is applied
2. Check database permissions for ALTER TABLE
3. Verify no conflicting migrations

## Summary

✅ **Unique Views Tracking**: Complete
- Database field added
- Aggregation task updated
- Dashboard displays both metrics
- Real-time calculation for today

✅ **Chart Rendering**: Fixed
- Dates serialized to ISO strings
- JavaScript can parse and sort dates
- Charts render properly

✅ **UI Improvements**: Complete
- Summary cards show unique visitors
- Table shows both total and unique views
- Empty states updated

✅ **Security**: Verified
- CodeQL scan: 0 vulnerabilities
- No new security risks introduced

---

**Status**: ✅ Complete and Tested
**Migration**: 0013_add_unique_view_count.py
**Security**: ✅ CodeQL Passed (0 alerts)
