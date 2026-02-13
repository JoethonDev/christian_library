# Search Improvements - Bug Fixes and Relevance Tuning

## Issues Addressed

This document describes the fixes for two critical search issues reported by users.

### Issue 1: Tag Search Returns Empty Results

**Problem:**
When users clicked on tags from the home page, the search page showed empty results instead of displaying content with that tag.

**Root Cause:**
The `get_search_results()` method in `services.py` had an overly restrictive condition:

```python
if not any([search_query, content_type_filter, tag_filter]):
    return {
        'results': [],
        'available_tags': [],
        'pagination': None,
        'total_count': 0
    }
```

When clicking a tag from the home page, the URL was `?tag={tag_id}` with no search query. The condition required at least one parameter, but then the code tried to execute `search_optimized(empty_query, ...)` which would work fine. The early return prevented legitimate tag-only searches.

**Solution:**
Removed the restrictive condition entirely. The `search_optimized()` method handles empty queries correctly by returning all active content (ordered by date), which is then filtered by the tag on line 266.

**Code Change:**
```python
# Before:
if not any([search_query, content_type_filter, tag_filter]):
    return {'results': [], ...}

# After:
# Allow search by tag filter alone (without search query)
# Removed restrictive condition
```

**Test:**
```python
def test_tag_only_search_returns_results(self):
    """Test that searching by tag alone returns results"""
    results = service.get_search_results(
        search_query='',
        tag_filter=str(self.tag1.id)
    )
    self.assertGreater(results['total_count'], 0)
```

---

### Issue 2: Search Results Too Broad (Low Relevance)

**Problem:**
When searching for "ترنيمة ميلاد المسيح في بيت لحم" (Christmas carol in Bethlehem), results also included unrelated content like "يونان النبي" (Jonah the prophet). The user wanted results with 85-90% similarity, not loosely related items.

**Root Cause:**
The Full-Text Search (FTS) rank threshold was set too low at `0.01` (1% relevance). This meant that any content with even the slightest match would appear in results, including documents that only shared common Arabic stop words.

**Solution:**
Increased `FTS_RANK_THRESHOLD` from `0.01` to `0.1` (10% minimum relevance). This creates a stricter filter that only shows results with meaningful relevance to the search query.

**Why 0.1 (10%) instead of 0.85-0.9 (85-90%)?**
- PostgreSQL FTS ranking is not a percentage similarity score
- Rank values are calculated based on:
  - Term frequency (how often search terms appear)
  - Document length normalization
  - Field weights (title=A, description=B, etc.)
- A rank of 0.1 is already quite strict in practice
- Values of 0.85-0.9 would be extremely restrictive and likely return no results for most queries
- The 0.1 threshold provides a good balance between precision (relevant results) and recall (finding enough results)

**Code Change:**
```python
# Before:
FTS_RANK_THRESHOLD = 0.01  # 1% relevance

# After:
FTS_RANK_THRESHOLD = 0.1  # 10% relevance - stricter for better precision
```

**Test:**
```python
def test_search_relevance_threshold(self):
    """Test that search returns only relevant results"""
    results = ContentItem.objects.search_optimized("ترنيمة ميلاد المسيح")
    
    # Christmas item should be in results
    self.assertIn(self.christmas_item, results)
    
    # Jonah item should NOT be in results (different topic)
    self.assertNotIn(self.jonah_item, results)
```

---

### Issue 3: Results Not Ordered by Relevance

**Problem:**
Search results appeared to prefer PDFs over other media types, and the ordering didn't consistently show most relevant results first.

**Root Cause:**
The sorting logic in `get_search_results()` was incorrectly overriding the FTS ranking:

```python
# Problematic condition:
if sort_by in ['title_ar', 'title_en'] or (not search_query or content_type_filter != 'pdf'):
    # This always re-sorted, losing FTS rank order
    results_qs = results_qs.order_by('-created_at')
```

This meant that even when `search_optimized()` returned results sorted by rank, they were immediately re-sorted by date, losing the relevance ordering.

**Solution:**
Fixed the sorting logic to preserve FTS ranking when a search query is provided:

```python
# New logic:
if not search_query:
    # No search query - sort by date or specified field
    results_qs = results_qs.order_by('-created_at')
elif sort_by in ['title_ar', 'title_en']:
    # User explicitly wants to sort by title
    results_qs = results_qs.order_by(sort_by)
# else: keep the FTS ranking order from search_optimized (-rank, -created_at)
```

**Result Order:**
1. **Primary**: FTS rank (relevance score) - highest first
2. **Secondary**: Creation date - newest first (for items with same rank)

**No Content Type Preference:**
All content types (PDF, video, audio) are treated equally in ranking. The rank is based solely on:
- How well the content matches the search terms
- Which fields contain the matches (title matches rank higher than description)
- Term frequency and document length

**Test:**
```python
def test_results_ordered_by_relevance(self):
    """Test that results are ordered by relevance"""
    exact_match = ContentItem.objects.create(
        title_ar="ترنيمة ميلاد المسيح",  # Exact match
        ...
    )
    partial_match = ContentItem.objects.create(
        title_ar="ميلاد",  # Partial match
        ...
    )
    
    results = list(ContentItem.objects.search_optimized("ترنيمة ميلاد المسيح"))
    
    # Exact match should come before partial match
    self.assertLess(exact_match_index, partial_match_index)
```

---

## Summary of Changes

### Files Modified

1. **`backend/apps/media_manager/models.py`**
   - Changed `FTS_RANK_THRESHOLD` from `0.01` to `0.1`
   - Updated comment to reflect new 10% minimum relevance

2. **`backend/apps/frontend_api/services.py`**
   - Removed restrictive condition that prevented tag-only searches
   - Fixed sorting logic to preserve FTS ranking
   - Added clear comments explaining the sorting behavior

3. **`backend/apps/media_manager/test_search.py`**
   - Added `TagSearchFixTest` class with 3 test methods
   - Added `SearchAPIIntegrationTest` class with 1 test method
   - All tests verify the fixes work correctly

### Expected Behavior

**Before Fixes:**
- ❌ Clicking tags → Empty results
- ❌ Search "Christmas carol" → Also shows "Jonah the prophet"
- ❌ Results not ordered by relevance

**After Fixes:**
- ✅ Clicking tags → Shows all content with that tag
- ✅ Search "Christmas carol" → Only shows Christmas-related content (10%+ relevance)
- ✅ Results ordered by: relevance score first, then date

### Testing

Run the new tests to verify fixes:

```bash
python manage.py test apps.media_manager.test_search.TagSearchFixTest
python manage.py test apps.media_manager.test_search.SearchAPIIntegrationTest
```

---

## Technical Details

### PostgreSQL FTS Ranking

The FTS ranking algorithm uses the following formula:

```
rank = weight_A × (tf_title / doc_length_title) +
       weight_B × (tf_desc / doc_length_desc) +
       weight_C × (tf_transcript / doc_length_transcript) +
       weight_D × (tf_notes / doc_length_notes)
```

Where:
- `tf` = term frequency (how many times search terms appear)
- `doc_length` = total words in that field
- `weight_A` = 1.0 (highest weight for titles)
- `weight_B` = 0.4
- `weight_C` = 0.2
- `weight_D` = 0.1

### Threshold Interpretation

- **0.01 (old)**: Very permissive - any tiny match passes
- **0.1 (new)**: Moderate - requires meaningful term presence
- **0.5**: Strict - requires strong term coverage
- **0.85-0.9**: Extremely strict - rarely any results

The 0.1 threshold is a practical middle ground that filters out noise while still returning useful results.

---

## Migration Notes

These changes are **backward compatible** and require no database migrations. The changes only affect:
1. In-memory query filtering (threshold value)
2. Query result ordering (sort logic)
3. Early return conditions (service layer)

Existing search vectors and indexes continue to work without modification.
