# Search & SEO Requirements for Django SSR Application

## Overview
This document defines all required work to:
1. Make the application discoverable by Google Search (SEO for SSR Django).
2. Enable full‑text search inside book contents with ranking.

Constraints:
- **Server**: 2 vCPU, 4 GB RAM
- **Backend**: Django (SSR using templates)
- **Content**: Books (PDF / text-based content)
- **Goal**: Low infrastructure cost, minimal operational complexity

---

## Part 1: Google Search Visibility (SEO)

### Goal
Ensure that:
- Pages are crawlable by Google
- Book pages appear in search results
- New books are indexed automatically

---

### 1. URL & Page Structure (Required)

#### Work
- Ensure **one public URL per book**
- URLs must be stable and human-readable

#### Example
```
/books/<slug>/
```

#### Tools
- Django URL routing
- `slugify`

#### Complexity
Low

---

### 2. Server‑Side Rendering Validation (Already Supported)

Since Django templates render HTML server‑side:
- Google **can index content directly**
- No additional SSR framework required

#### Action
None (just verify pages are public)

---

### 3. HTML Meta Tags (Critical)

#### Work
Add dynamic SEO metadata per page:

- `<title>`
- `<meta name="description">`
- `<meta name="keywords">`

#### Implementation
- Base template with blocks
- Populate from book model

#### Example
```html
<title>{{ book.title }} | Library</title>
<meta name="description" content="{{ book.summary|truncatechars:160 }}">
```

#### Tools
- Django templates

#### Complexity
Low

---

### 4. OpenGraph & Schema Markup (Optional but Recommended)

#### Work
Add structured data to improve ranking and previews

- OpenGraph tags
- JSON‑LD Schema (Book)

#### Tools
- Django templates
- JSON‑LD

#### Complexity
Medium

---

### 5. Sitemap Generation (Required)

#### Work
- Auto‑generate sitemap.xml
- Include:
  - Home
  - Book listing
  - Each book detail page

#### Tools
- `django.contrib.sitemaps`

#### Implementation Steps
1. Enable sitemap app
2. Create sitemap classes
3. Expose `/sitemap.xml`

#### Complexity
Low

---

### 6. robots.txt (Required)

#### Work
- Allow crawling of public pages
- Block admin/private pages

#### Example
```
User-agent: *
Disallow: /admin/
Allow: /
```

#### Complexity
Low

---

### 7. Google Search Console (External)

#### Work
- Register domain
- Submit sitemap
- Monitor indexing

#### Tools
- Google Search Console

#### Complexity
Low (manual)

---

### Estimated Effort (SEO)

| Item | Time |
|-----|-----|
| URLs & Metadata | 1 day |
| Sitemap + robots | 0.5 day |
| Schema | 1 day |
| Search Console | 0.5 day |
| **Total** | **2–3 days** |

---

## Part 2: Full‑Text Search Inside Books

### Goal
Enable users to search for words inside book contents with ranking.

---

## Recommended Approach (Weak Server Friendly)

### ✅ PostgreSQL Full‑Text Search (FTS)

Why:
- Already available
- No extra services
- Low RAM usage
- Fast for text search

---

### 1. Book Content Extraction

#### Work
Extract text from books:

- PDF → text
- DOCX → text

#### Tools
- `pdfminer.six` or `pdftotext`
- `python-docx`

#### Output
- Store extracted text in DB

#### Complexity
Medium

---

### 2. Database Schema Changes

#### Work
Add fields:

```python
book_content = TextField()
search_vector = SearchVectorField()
```

#### Tools
- Django ORM
- PostgreSQL

#### Complexity
Medium

---

### 3. Search Vector Indexing

#### Work
- Create GIN index
- Populate search vectors

#### SQL
```sql
CREATE INDEX book_search_idx ON books USING GIN(search_vector);
```

#### Tools
- PostgreSQL

#### Complexity
Low

---

### 4. Search Query Implementation

#### Work
- Use `SearchQuery` + `SearchRank`
- Rank by relevance

#### Example
```python
Book.objects.annotate(
  rank=SearchRank(F('search_vector'), query)
).filter(rank__gte=0.1).order_by('-rank')
```

#### Tools
- `django.contrib.postgres.search`

#### Complexity
Medium

---

### 5. Search UI

#### Work
- Search input
- Result list with highlights

#### Tools
- Django templates
- `SearchHeadline`

#### Complexity
Low

---

### 6. Incremental Updates (Important)

#### Work
- Update search_vector when:
  - Book created
  - Book updated

#### Tools
- Django signals or save override

#### Complexity
Low

---

### Optional Enhancements

- Weight title higher than content
- Phrase search
- Language configuration

---

### Estimated Effort (Search)

| Item | Time |
|-----|-----|
| Content extraction | 2 days |
| DB changes & indexing | 1 day |
| Query logic | 1 day |
| UI | 1 day |
| **Total** | **4–5 days** |

---

## What NOT to Use (For This Server)

❌ Elasticsearch / OpenSearch
- High RAM usage
- Operational overhead

❌ External SaaS search
- Cost
- Data privacy concerns

---

## Refactoring Impact

| Area | Impact |
|-----|------|
| Models | Medium |
| Migrations | Required |
| Templates | Low |
| Infrastructure | Minimal |

---

## Final Recommendation

- Use **Django SSR + SEO best practices** for Google visibility
- Use **PostgreSQL Full‑Text Search** for book content search
- No extra servers required
- Scales safely on 2 vCPU / 4 GB RAM

---

## Next Steps

1. Confirm PostgreSQL version
2. Confirm book file formats
3. Decide ranking rules
4. Start SEO implementation first

