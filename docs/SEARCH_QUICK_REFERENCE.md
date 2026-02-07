# Search API Quick Reference

## Content Search

### Basic Search
```python
# Python
ContentItem.objects.search_optimized("query")

# API
GET /api/search/?q=query
```

### Filtered Search
```python
# By content type
ContentItem.objects.search_optimized("query", content_type="pdf")

# API
GET /api/search/?q=query&type=pdf
```

### Language-Specific
```python
# Explicit language
ContentItem.objects.search_optimized("query", language="arabic")

# API
GET /api/search/?q=query&language=ar
```

## Tag Search

### Search Tags
```python
# Python
Tag.objects.search_tags("query")

# API
GET /api/search/tags/?q=query
```

### With Language
```python
# Python
Tag.objects.search_tags("query", language="ar")

# API
GET /api/search/tags/?q=query&language=ar
```

## Search Vector Update

### Single Item
```python
item = ContentItem.objects.get(id=item_id)
item.update_search_vector()
item.save(update_fields=['search_vector'])
```

### Bulk Update
```python
for item in ContentItem.objects.all():
    item.update_search_vector()
    item.save(update_fields=['search_vector'])
```

## Searchable Fields

| Field | Weight | Language |
|-------|--------|----------|
| title_ar | A | Arabic |
| title_en | A | English |
| description_ar | B | Arabic |
| description_en | B | English |
| transcript | C | Simple |
| notes | D | Simple |
| book_content | D | Arabic |
| tags | - | Both |

## Response Format

### Content Search
```json
{
  "success": true,
  "results": [
    {
      "id": "uuid",
      "title": "Title",
      "description": "Description",
      "content_type": "pdf|video|audio",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

### Tag Search
```json
{
  "success": true,
  "query": "search term",
  "count": 5,
  "tags": [
    {
      "id": "uuid",
      "name": "Tag Name",
      "name_en": "English Name",
      "content_count": 10,
      "color": "#8C1C13"
    }
  ]
}
```

## Performance Tips

1. **Use Prefetch**: Tags are auto-prefetched in `search_optimized()`
2. **Paginate Results**: Limit to 12-20 items per page
3. **Cache Queries**: Use Redis for frequent searches
4. **Update Vectors**: Run migration after adding new fields

## Testing

```bash
# Run all search tests
python manage.py test apps.media_manager.test_search

# Specific test class
python manage.py test apps.media_manager.test_search.MultilingualSearchTest
```

## Common Queries

```python
# Search all content
ContentItem.objects.search_optimized("اللاهوت")

# Search videos only
ContentItem.objects.search_optimized("Theology", content_type="video")

# Search with ranking
from django.contrib.postgres.search import SearchQuery, SearchRank
query = SearchQuery("كتاب", config="arabic")
items = ContentItem.objects.active().annotate(
    rank=SearchRank(F('search_vector'), query)
).filter(rank__gte=0.01).order_by('-rank')

# Search tags
Tag.objects.search_tags("تاريخ")

# Autocomplete
ContentItem.objects.for_autocomplete("لاه", language="ar")
Tag.objects.for_autocomplete("Hist", language="en")
```
