# Multilingual Full-Text Search Documentation

## Overview

The Christian Library platform implements advanced multilingual full-text search (FTS) using PostgreSQL's built-in search capabilities. The search system supports both Arabic and English content, with intelligent language detection and proper ranking for all content types.

## Features

### ✅ Multilingual Support
- **Arabic**: Full support for Arabic text with diacritic normalization
- **English**: Full support for English text with stemming
- **Mixed Content**: Automatic language detection and multi-language indexing
- **Language-Specific Configs**: Uses PostgreSQL `arabic`, `english`, and `simple` text search configurations

### ✅ Comprehensive Field Coverage
Search indexes and queries across all relevant text fields:

| Field | Weight | Language Config | Description |
|-------|---------|-----------------|-------------|
| `title_ar` | A (highest) | Arabic | Arabic title |
| `title_en` | A (highest) | English | English title |
| `description_ar` | B (high) | Arabic | Arabic description |
| `description_en` | B (high) | English | English description |
| `transcript` | C (medium) | Simple | Audio/video transcripts |
| `notes` | D (low) | Simple | Study notes |
| `book_content` | D (low) | Arabic | Extracted PDF text content |
| `tags` | - | Both | Associated tag names (Arabic and English) |

### ✅ Search Features
- **Full-Text Search**: PostgreSQL FTS with GIN indexes for fast queries
- **Ranking**: Results ranked by relevance using weighted fields
- **Tag Search**: Dedicated tag search with content counts
- **Content Type Filtering**: Filter by video, audio, or PDF
- **Language Detection**: Automatic detection based on query content
- **Performance**: Sub-second response times with proper indexing

## API Endpoints

### 1. Global Content Search
**Endpoint**: `/api/search/`

**Method**: `GET`

**Query Parameters**:
- `q` (required): Search query
- `type` (optional): Content type filter (`video`, `audio`, `pdf`, `all`)
- `language` (optional): Language preference (`ar`, `en`)

**Example Request**:
```bash
# Search for theology content in Arabic
GET /api/search/?q=اللاهوت

# Search for videos in English
GET /api/search/?q=Theology&type=video&language=en
```

**Example Response**:
```json
{
  "success": true,
  "results": [
    {
      "id": "uuid",
      "title": "كتاب اللاهوت المسيحي",
      "description": "دراسة شاملة...",
      "content_type": "pdf",
      "tags": ["لاهوت", "عقيدة"]
    }
  ]
}
```

### 2. Tag Search
**Endpoint**: `/api/search/tags/`

**Method**: `GET`

**Query Parameters**:
- `q` (required): Search query (minimum 2 characters)
- `language` (optional): Language preference (`ar`, `en`)

**Example Request**:
```bash
# Search for tags containing "history"
GET /api/search/tags/?q=تاريخ

# Search with explicit language
GET /api/search/tags/?q=History&language=en
```

**Example Response**:
```json
{
  "success": true,
  "query": "تاريخ",
  "count": 2,
  "tags": [
    {
      "id": "uuid",
      "name": "تاريخ الكنيسة",
      "name_en": "Church History",
      "content_count": 15,
      "color": "#8C1C13"
    }
  ]
}
```

### 3. Search Autocomplete
**Endpoint**: `/search/autocomplete/`

**Method**: `GET`

**Query Parameters**:
- `q` (required): Partial query for autocomplete

**Example Request**:
```bash
GET /search/autocomplete/?q=لاه
```

**Example Response**:
```json
{
  "suggestions": [
    "كتاب اللاهوت المسيحي",
    "مقدمة في اللاهوت الأرثوذكسي"
  ]
}
```

## Usage Examples

### Python/Django

#### Basic Search
```python
from apps.media_manager.models import ContentItem

# Search for content
results = ContentItem.objects.search_optimized("اللاهوت")

# Search with content type filter
pdf_results = ContentItem.objects.search_optimized("Theology", content_type="pdf")

# Search with explicit language
arabic_results = ContentItem.objects.search_optimized("كتاب", language="arabic")
```

#### Tag Search
```python
from apps.media_manager.models import Tag

# Search tags
tags = Tag.objects.search_tags("تاريخ")

# Get tags with content counts
for tag in tags:
    print(f"{tag.name_ar}: {tag.content_count} items")
```

#### Advanced Search with Ranking
```python
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F

query = SearchQuery("اللاهوت", config="arabic")
results = ContentItem.objects.active().annotate(
    rank=SearchRank(F('search_vector'), query)
).filter(rank__gte=0.01).order_by('-rank')
```

### JavaScript/Frontend

#### Global Search
```javascript
// Fetch search results
async function searchContent(query, type = 'all') {
    const response = await fetch(`/api/search/?q=${encodeURIComponent(query)}&type=${type}`);
    const data = await response.json();
    
    if (data.success) {
        return data.results;
    }
    throw new Error(data.error);
}

// Usage
const results = await searchContent('اللاهوت');
```

#### Tag Search
```javascript
// Search for tags
async function searchTags(query) {
    const response = await fetch(`/api/search/tags/?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    
    if (data.success) {
        return data.tags;
    }
    throw new Error(data.error);
}

// Usage with autocomplete
const tags = await searchTags('تاريخ');
tags.forEach(tag => {
    console.log(`${tag.name}: ${tag.content_count} items`);
});
```

#### Autocomplete
```javascript
// Autocomplete suggestions
async function getAutocomplete(query) {
    const response = await fetch(`/search/autocomplete/?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    return data.suggestions;
}

// Usage with debouncing
let timeoutId;
searchInput.addEventListener('input', (e) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(async () => {
        const suggestions = await getAutocomplete(e.target.value);
        displaySuggestions(suggestions);
    }, 300);
});
```

## Search Vector Management

### Automatic Updates
Search vectors are automatically updated when:
- New content is created
- Content fields are modified (title, description, etc.)
- Tags are added or removed (future enhancement)

### Manual Update
To manually update search vectors for existing content:

```python
from apps.media_manager.models import ContentItem

# Update single item
item = ContentItem.objects.get(id=item_id)
item.update_search_vector()
item.save(update_fields=['search_vector'])

# Bulk update all items
for item in ContentItem.objects.all():
    item.update_search_vector()
    item.save(update_fields=['search_vector'])
```

### Database Migration
A data migration is included to update all existing content with the new multilingual search vectors:

```bash
python manage.py migrate media_manager 0015_update_search_vector_multilingual
```

## Performance Optimization

### Indexes
The system uses several indexes for optimal performance:

1. **GIN Index**: On `search_vector` field for FTS queries
2. **Trigram Indexes**: On `title_ar`, `description_ar`, `book_content` for fuzzy matching
3. **Composite Indexes**: For filtering by active status and content type
4. **Partial Indexes**: For active content only (reduces index size)

### Query Optimization
- **Prefetch Related**: Tags are prefetched to avoid N+1 queries
- **Select Related**: Media metadata is included in single query
- **Pagination**: Results are paginated (12 items per page by default)
- **Caching**: Search results can be cached (Redis integration)

### Performance Targets
- **Typical queries**: < 100ms
- **Complex queries with filters**: < 500ms
- **Large result sets (100+ items)**: < 1s

## Language Detection

The search system automatically detects the query language:

```python
import re

def detect_language(query):
    """Detect if query contains Arabic characters"""
    has_arabic = bool(re.search(r'[\u0600-\u06FF\u0750-\u077F]', query))
    return 'arabic' if has_arabic else 'english'
```

- **Arabic Range**: Unicode ranges U+0600–U+06FF (Arabic) and U+0750–U+077F (Arabic Supplement)
- **Default**: If no Arabic characters detected, assumes English

## Search Ranking

Results are ranked by relevance using weighted field matching:

### Weight Schema
- **Weight A (1.0)**: Titles (highest importance)
- **Weight B (0.4)**: Descriptions
- **Weight C (0.2)**: Transcripts
- **Weight D (0.1)**: Notes and book content

### Ranking Formula
```sql
rank = 
    setweight(to_tsvector('arabic', title_ar), 'A') +
    setweight(to_tsvector('english', title_en), 'A') +
    setweight(to_tsvector('arabic', description_ar), 'B') +
    setweight(to_tsvector('english', description_en), 'B') +
    setweight(to_tsvector('simple', transcript), 'C') +
    setweight(to_tsvector('simple', notes), 'D') +
    setweight(to_tsvector('arabic', book_content), 'D')
```

### Threshold
- Minimum rank threshold: `0.001` (very inclusive to catch all relevant results)
- Results are ordered by: `rank DESC, created_at DESC`

## Advanced Features

### Arabic Text Normalization
The system includes custom PostgreSQL functions for Arabic text processing:

```sql
-- Remove Arabic diacritics
CREATE FUNCTION arabic_normalize(text) RETURNS text AS $$
    SELECT regexp_replace($1, '[\u064B-\u0652\u0670]', '', 'g')
$$ LANGUAGE SQL IMMUTABLE;

-- Calculate similarity for fuzzy matching
CREATE FUNCTION arabic_similarity(text, text) RETURNS float AS $$
    SELECT similarity(arabic_normalize($1), arabic_normalize($2))
$$ LANGUAGE SQL IMMUTABLE;
```

### Fuzzy Matching
For partial word matches and typos, the system uses PostgreSQL's `pg_trgm` extension:

```python
from django.contrib.postgres.search import TrigramSimilarity

# Fuzzy search with similarity threshold
results = ContentItem.objects.annotate(
    similarity=TrigramSimilarity('title_ar', query)
).filter(similarity__gt=0.3).order_by('-similarity')
```

## Testing

Comprehensive tests are available in `apps/media_manager/test_search.py`:

```bash
# Run all search tests
python manage.py test apps.media_manager.test_search

# Run specific test class
python manage.py test apps.media_manager.test_search.MultilingualSearchTest

# Run specific test
python manage.py test apps.media_manager.test_search.MultilingualSearchTest.test_arabic_title_search
```

### Test Coverage
- ✅ Arabic text search
- ✅ English text search
- ✅ Mixed-language search
- ✅ Tag search and filtering
- ✅ Content type filtering
- ✅ Ranking and relevance
- ✅ Performance and query optimization
- ✅ API endpoints

## Troubleshooting

### Search Returns No Results

1. **Check PostgreSQL**: Ensure PostgreSQL is being used (not SQLite)
2. **Verify Search Vectors**: Run migration to update search vectors
   ```bash
   python manage.py migrate media_manager
   ```
3. **Check Content Status**: Ensure content `is_active=True`
4. **Inspect Query**: Try with simpler queries first

### Slow Search Performance

1. **Check Indexes**: Verify GIN index exists on `search_vector`
   ```sql
   SELECT indexname FROM pg_indexes WHERE tablename = 'media_manager_contentitem';
   ```
2. **Analyze Query Plan**: Use `EXPLAIN ANALYZE` to identify bottlenecks
3. **Enable Query Caching**: Configure Redis cache for frequent searches
4. **Consider Pagination**: Limit result set size

### Language Detection Issues

1. **Override Detection**: Specify `language` parameter explicitly
   ```python
   results = ContentItem.objects.search_optimized(query, language='arabic')
   ```
2. **Check Character Encoding**: Ensure UTF-8 encoding throughout
3. **Verify Text Config**: Check PostgreSQL text search configurations:
   ```sql
   SELECT * FROM pg_ts_config WHERE cfgname IN ('arabic', 'english', 'simple');
   ```

## Future Enhancements

### Planned Features
- [ ] Real-time search vector updates when tags change
- [ ] Search result highlighting in UI
- [ ] Advanced filters (date range, author, etc.)
- [ ] Search analytics and popular queries
- [ ] Synonym support for better matching
- [ ] Voice search integration

### Contributing

To extend the search functionality:

1. **Add New Searchable Field**: 
   - Update `update_search_vector()` method in `models.py`
   - Create migration to update existing records
   - Add tests for new field

2. **Add New Search Filter**:
   - Update `search_optimized()` queryset method
   - Add URL parameter handling in view
   - Update API documentation

3. **Optimize Performance**:
   - Profile slow queries with Django Debug Toolbar
   - Add strategic indexes for new filters
   - Consider materialized views for complex aggregations

## References

- [PostgreSQL Full-Text Search](https://www.postgresql.org/docs/current/textsearch.html)
- [Django PostgreSQL Search](https://docs.djangoproject.com/en/stable/ref/contrib/postgres/search/)
- [Arabic Text Processing](https://en.wikipedia.org/wiki/Arabic_diacritics)
- [pg_trgm Extension](https://www.postgresql.org/docs/current/pgtrgm.html)

## Support

For issues or questions about the search functionality:
- Open an issue on GitHub
- Check existing documentation in `/docs`
- Review test cases in `test_search.py`
