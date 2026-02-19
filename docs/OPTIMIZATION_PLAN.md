# Django Query Optimization & Refactoring Plan

## Purpose
This document provides a comprehensive plan to audit, refactor, and optimize Django views and ORM usage for improved database performance, based on issues identified in db_query_metrics.jsonl logs.

---

## 1. Common Issues & Best-Practice Patterns

### 1.1 N+1 Query Problem
- **Symptom:** Multiple queries for related objects (e.g., accessing `.user`, `.tags` in a loop).
- **Solution:** Use `select_related` (ForeignKey/OneToOne) and `prefetch_related` (ManyToMany/Reverse FK).

### 1.2 Unindexed Fields
- **Symptom:** Filtering or ordering on fields without DB indexes.
- **Solution:** Add `db_index=True` to model fields used in filters/order_by.

### 1.3 Large Unpaginated Querysets
- **Symptom:** Fetching all records at once, causing memory/performance issues.
- **Solution:** Use Django’s `Paginator` for all list views.

### 1.4 Redundant Queries
- **Symptom:** Repeated queries for the same data in a single request.
- **Solution:** Query once, reuse result in context.

### 1.5 Missing Aggregations
- **Symptom:** Aggregating/counting in Python instead of SQL.
- **Solution:** Use `annotate`/`aggregate` in queryset.

### 1.6 Inefficient Filtering
- **Symptom:** Filtering in Python after fetching all objects.
- **Solution:** Filter in the queryset at the DB level.

### 1.7 Lack of Caching
- **Symptom:** Expensive queries run on every request.
- **Solution:** Use Django’s cache framework for expensive/rarely-changing queries.

---

## 2. Step-by-Step Audit & Refactoring Checklist

### 2.1 Collect Metrics
- [ ] Review db_query_metrics.jsonl for slow queries, high query counts, and repeated patterns.

### 2.2 Audit Each View/Function
For each view:
- [ ] Check for N+1 queries (look for related object access in loops).
- [ ] Ensure all list views use pagination.
- [ ] Check for redundant queries.
- [ ] Review filters/order_by for missing indexes.
- [ ] Look for Python-side aggregation/filtering.
- [ ] Identify expensive queries for caching.

### 2.3 Refactor According to Patterns
- [ ] Apply the expected pattern for each issue found.

### 2.4 Test & Benchmark
- [ ] After each refactor, test the view and benchmark query count and duration.

### 2.5 Document Changes
- [ ] Keep a changelog of optimizations for future reference.

---

## 3. Example Refactor Patterns

### 3.1 N+1 Query Problem
**Before:**
```python
def content_list(request):
  items = ContentItem.objects.all()
  for item in items:
    print(item.tags.all())  # N+1 problem
  return render(request, 'list.html', {'items': items})
```
**After:**
```python
def content_list(request):
  items = ContentItem.objects.prefetch_related('tags').all()
  return render(request, 'list.html', {'items': items})
```

### 3.2 Pagination
**Before:**
```python
items = ContentItem.objects.all()
```
**After:**
```python
from django.core.paginator import Paginator
paginator = Paginator(ContentItem.objects.all(), 20)
page = request.GET.get('page', 1)
items = paginator.get_page(page)
```

### 3.3 Aggregation
**Before:**
```python
count = 0
for item in ContentItem.objects.all():
  if item.is_active:
    count += 1
```
**After:**
```python
count = ContentItem.objects.filter(is_active=True).count()
```

### 3.4 Caching
**Before:**
```python
stats = get_expensive_stats()
```
**After:**
```python
from django.core.cache import cache
stats = cache.get('expensive_stats')
if stats is None:
  stats = get_expensive_stats()
  cache.set('expensive_stats', stats, 3600)
```

---

## 4. General Django ORM Optimization Tips
- Use `select_related`/`prefetch_related` for related objects in lists.
- Paginate all list views.
- Add indexes to frequently filtered/ordered fields.
- Use `annotate`/`aggregate` for counts and summaries.
- Cache expensive or rarely-changing queries.
- Avoid filtering/aggregation in Python when it can be done in SQL.

---

## 5. Next Steps
- [ ] Start auditing each function/view using the above checklists.
- [ ] Refactor as needed.
- [ ] Test and benchmark after each change.
- [ ] Update this document with findings and progress.

---

## 6. Changelog
- Use this section to record each optimization and its impact.



## Optimization Map: Minimal Change Strategy

This section lists files and functions in the frontend_api app that should be optimized for query efficiency. The focus is on minimal, maintainable changes: e.g., extracting common query logic, using select_related/prefetch_related, and reusing helper functions for repeated query patterns.

### Target Files & Functions

1. **views.py** (this file)
  - `home`: Use helper for latest content queries (DRY for video/audio/pdf)
  - `videos`, `audios`, `pdfs`: Extract paginated, filtered queryset logic into a reusable function
  - `video_detail`, `audio_detail`: Use helper for related content queries
  - `tag_content`, `search`: Centralize tag/content filtering logic

2. **admin_views.py**
  - `content_list`, `video_management`, `audio_management`, `pdf_management`: Use shared paginated query helpers
  - `content_detail`: Use select_related/prefetch_related for meta/tags

3. **media_manager/views.py**
  - `ContentListAPIView`: Use paginated, filtered queryset helper
  - `MediaPlayerView`: Use select_related for meta

### Minimal Change Patterns
- Create a helper function for paginated, filtered content queries (by type, tag, search)
- Use select_related/prefetch_related in all list/detail views
- Reuse tag/content filtering logic across views
- Replace repeated aggregation/counts with annotate/aggregate
- Add caching only for expensive, rarely-changing queries

---
---