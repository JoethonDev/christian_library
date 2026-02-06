# PDF Text Extraction Refactoring - Implementation Guide

## Overview

This document describes the refactoring of PDF text extraction processing in the Christian Library application. The refactoring improves code organization, enhances search capabilities, and provides better support for Arabic text processing with OCR.

## Table of Contents

1. [Architecture Changes](#architecture-changes)
2. [Features Implemented](#features-implemented)
3. [API Documentation](#api-documentation)
4. [Usage Examples](#usage-examples)
5. [Technical Details](#technical-details)
6. [Testing](#testing)

---

## Architecture Changes

### Before Refactoring

- PDF processing logic was embedded in `ContentItem` model methods
- ~300 lines of OCR and text processing code in models.py
- Mixed concerns between data models and business logic
- Limited search capabilities (title/description only)

### After Refactoring

- Dedicated `PdfProcessorService` for all PDF processing operations
- Cleaner separation of concerns
- Enhanced search with two modes: title search and full-text content search
- Better maintainability and testability

### New Components

1. **PdfProcessorService** (`apps/media_manager/services/pdf_processor_service.py`)
   - Handles PDF text extraction
   - Manages OCR processing with Tesseract
   - Integrates with Arabic text cleaning pipeline

2. **PDFContentSearchAPIView** (`apps/media_manager/views.py`)
   - Dedicated API endpoint for PDF content search
   - Context snippet extraction
   - Search result highlighting

3. **Enhanced Admin UI** (`templates/admin/pdf_management.html`)
   - Search mode toggle (title vs. content)
   - Visual feedback for active search mode
   - HTMX integration for seamless updates

---

## Features Implemented

### 1. PDF Text Extraction

**Multiple Extraction Methods:**
- PyMuPDF (fitz) - Primary method for digital PDFs
- pdfminer - Fallback for complex layouts
- Tesseract OCR - For scanned/image-based PDFs

**Intelligent Fallback:**
```python
# Heuristic: if text is too short, try OCR
threshold = max(500, page_count * 300)
if len(best_text) < threshold:
    # Attempt OCR extraction
    text_ocr = self._extract_with_ocr(pdf_path)
```

**Image Preprocessing for OCR:**
- Grayscale conversion
- Noise removal with denoising
- Adaptive thresholding for binarization
- Automatic deskewing (rotation correction)

**OCR Confidence Scoring:**
- Dual PSM modes (6 and 3) with adaptive fallback
- Confidence calculation from Tesseract TSV output
- Automatic selection of best result

### 2. Arabic Text Normalization

**Comprehensive Cleaning Pipeline:**

1. **Structural Noise Removal:**
   - OCR hallucinations and gibberish
   - Watermarks and URLs
   - Metadata tags and page numbers
   - Copyright notices

2. **Character Normalization:**
   ```python
   ARABIC_NORMALIZATION = {
       "أ": "ا", "إ": "ا", "آ": "ا",  # Alif variations
       "ى": "ي", "ة": "ه",              # Yaa and Teh marbuta
       "ؤ": "و", "ئ": "ي",              # Hamza variations
   }
   ```

3. **Diacritics Removal:**
   - Removes tashkeel marks for consistent search
   - Maintains text readability

4. **Liturgical Corrections:**
   - Fixes common OCR errors in religious terms
   - Corrects Coptic Orthodox terminology

### 3. Full-Text Search

**PostgreSQL FTS Integration:**
```python
# Arabic-configured full-text search
search_query_obj = SearchQuery(query, config='arabic')
results = ContentItem.objects.filter(
    search_vector__isnull=False
).annotate(
    rank=SearchRank(F('search_vector'), search_query_obj)
).filter(rank__gte=0.1).order_by('-rank')
```

**Search Vector:**
- Weighted fields: A (title), B (description), C (content)
- Automatic updates via background tasks
- Optimized GIN indexes for fast search

### 4. Search Result Enhancement

**Context Snippets:**
```python
def _extract_context_snippet(text, query, context_length=200):
    # Finds query in text
    # Extracts surrounding context
    # Adds ellipsis as needed
    return snippet
```

**Result Highlighting:**
```python
def _highlight_text(text, query):
    # Wraps matches in <mark> tags
    pattern = re.compile(f'({escaped_query})', re.IGNORECASE)
    return pattern.sub(r'<mark>\1</mark>', text)
```

---

## API Documentation

### 1. PDF Content Search API

**Endpoint:** `GET /api/pdf/search/`

**Parameters:**
- `q` (required): Search query
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Results per page (default: 20, max: 100)
- `language` (optional): Display language (default: 'ar')

**Request Example:**
```bash
curl "http://localhost:8000/api/pdf/search/?q=القداس&page=1&page_size=10&language=ar"
```

**Response Example:**
```json
{
  "success": true,
  "query": "القداس",
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "كتاب القداس الإلهي",
      "description": "شرح تفصيلي للقداس الإلهي",
      "snippet": "...في القداس الإلهي نتناول جسد ودم المسيح...",
      "highlighted_snippet": "...في <mark>القداس</mark> الإلهي نتناول...",
      "created_at": "2024-01-15T10:30:00Z",
      "tags": [
        {"id": "...", "name": "طقوس"}
      ],
      "meta": {
        "page_count": 150,
        "file_size_mb": 5,
        "processing_status": "completed"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 10,
    "total_results": 42,
    "total_pages": 5,
    "has_next": true,
    "has_previous": false
  }
}
```

### 2. Management Command: Reprocess PDFs

**Command:** `python manage.py reprocess_pdfs`

**Options:**
```bash
# Process all PDFs without content
python manage.py reprocess_pdfs

# Force reprocess all PDFs
python manage.py reprocess_pdfs --force-all

# Process specific PDF by ID
python manage.py reprocess_pdfs --content-id=550e8400-e29b-41d4-a716-446655440000

# Process synchronously (for debugging)
python manage.py reprocess_pdfs --sync

# Dry run (show what would be processed)
python manage.py reprocess_pdfs --dry-run

# Custom batch size
python manage.py reprocess_pdfs --batch-size=20
```

### 3. Background Task: Extract and Index

**Celery Task:** `extract_and_index_contentitem`

**Usage:**
```python
from apps.media_manager.tasks import extract_and_index_contentitem

# Queue extraction for a content item
task = extract_and_index_contentitem.delay(content_item_id)

# Get task status
task_result = task.result
```

**Task Flow:**
1. Extract text from PDF (PyMuPDF → pdfminer → OCR)
2. Apply Arabic text cleaning pipeline
3. Update `book_content` field
4. Generate search vector
5. Save to database
6. Update task monitor

---

## Usage Examples

### 1. Search Within PDF Content (Admin UI)

1. Navigate to: `/en/dashboard/pdfs/`
2. Enter search term in the search box
3. Click the dropdown button next to search
4. Select "Search Within PDF Content"
5. Results will show PDFs containing the search term
6. Switch back to "Search Titles & Descriptions" for title search

### 2. Programmatic PDF Processing

```python
from apps.media_manager.services import create_pdf_processor

# Create processor instance
processor = create_pdf_processor(content_item_id)

# Extract text from PDF
pdf_path = "/path/to/document.pdf"
extracted_text = processor.extract_text_from_pdf(pdf_path, page_count=100)

# Text is automatically cleaned and normalized
print(f"Extracted {len(extracted_text)} characters")
```

### 3. Search Integration in Views

```python
from django.contrib.postgres.search import SearchQuery, SearchRank
from apps.media_manager.models import ContentItem

def search_pdfs(query):
    search_query_obj = SearchQuery(query, config='arabic')
    
    results = ContentItem.objects.filter(
        content_type='pdf',
        is_active=True,
        search_vector__isnull=False
    ).annotate(
        rank=SearchRank(F('search_vector'), search_query_obj)
    ).filter(rank__gte=0.1).order_by('-rank')
    
    return results
```

---

## Technical Details

### Database Schema

**ContentItem Model Fields:**
```python
class ContentItem(models.Model):
    # ...existing fields...
    
    # New/Updated fields for PDF search
    book_content = models.TextField(
        blank=True,
        verbose_name=_('Book Content')
    )
    
    search_vector = SearchVectorField(
        null=True,
        blank=True
    )
```

**Database Indexes:**
```sql
-- GIN index for full-text search
CREATE INDEX IF NOT EXISTS contentitem_search_vector_idx 
ON media_manager_contentitem 
USING GIN (search_vector);
```

### Text Processing Pipeline

```
PDF File
  ↓
[PyMuPDF Extraction]
  ↓
[pdfminer Fallback]
  ↓
[Quality Check] → (if insufficient) → [Tesseract OCR]
  ↓
[Arabic Text Filter]
  ↓
[Structural Noise Removal]
  ↓
[Character Normalization]
  ↓
[Diacritics Removal]
  ↓
[Liturgical Corrections]
  ↓
[Whitespace Normalization]
  ↓
Cleaned Text → Database (book_content)
  ↓
[Search Vector Generation]
  ↓
Search Index (search_vector)
```

### Performance Considerations

**Extraction Performance:**
- PyMuPDF: ~0.1s per page (fast)
- pdfminer: ~0.2s per page (moderate)
- OCR: ~2-5s per page (slow, but necessary for scans)

**Optimization Strategies:**
1. **Batch Processing:**
   - Process multiple PDFs concurrently
   - Configurable batch sizes

2. **Caching:**
   - Search results cached for 5 minutes
   - Content statistics cached for 30 minutes

3. **Background Processing:**
   - All extraction runs in Celery tasks
   - Non-blocking user experience

4. **Database Optimization:**
   - GIN indexes for FTS
   - Proper field indexing
   - Query optimization with select_related/prefetch_related

### Error Handling

**Extraction Errors:**
```python
try:
    processor = create_pdf_processor(content_item_id)
    text = processor.extract_text_from_pdf(pdf_path, page_count)
except FileNotFoundError:
    # Handle missing PDF file
    logger.error(f"PDF file not found: {pdf_path}")
except Exception as e:
    # Handle other errors
    logger.error(f"Extraction failed: {e}", exc_info=True)
```

**Fallback Strategies:**
1. PyMuPDF fails → Try pdfminer
2. Both fail → Try OCR
3. OCR unavailable → Log warning, return empty string
4. PostgreSQL unavailable → Use simple ILIKE search

---

## Testing

### Unit Tests (To Be Added)

**Test Coverage Areas:**
1. PDF Processor Service
   - Text extraction methods
   - OCR processing
   - Image preprocessing
   - Confidence calculation

2. Search Functionality
   - FTS query building
   - Context snippet extraction
   - Result highlighting
   - Pagination

3. Arabic Text Processing
   - Normalization
   - Noise removal
   - Liturgical corrections

**Example Test:**
```python
def test_pdf_extraction():
    processor = create_pdf_processor("test-id")
    text = processor.extract_text_from_pdf("test.pdf", 10)
    assert len(text) > 0
    assert "القداس" in text  # Expected term
```

### Integration Tests (To Be Added)

**Test Scenarios:**
1. End-to-end PDF upload and processing
2. Search API with various queries
3. Admin UI search mode switching
4. Background task execution

### Manual Testing Checklist

- [ ] Upload a scanned Arabic PDF
- [ ] Verify OCR extraction triggers
- [ ] Check extracted text in database
- [ ] Test title search mode
- [ ] Test content search mode
- [ ] Verify search results highlighting
- [ ] Check pagination works correctly
- [ ] Test with long queries
- [ ] Test with special characters
- [ ] Verify performance with large PDFs

---

## Maintenance

### Monitoring

**Key Metrics:**
1. Extraction success rate
2. Average processing time per page
3. OCR confidence scores
4. Search query performance
5. Background task queue length

**Log Locations:**
```python
# Application logs
logger = logging.getLogger('apps.media_manager')

# Task logs
logger = logging.getLogger('apps.media_manager.tasks')

# Service logs
logger = logging.getLogger('apps.media_manager.services.pdf_processor_service')
```

### Troubleshooting

**Common Issues:**

1. **OCR Not Working:**
   - Check Tesseract installation: `tesseract --version`
   - Verify Arabic language data: `tesseract --list-langs`
   - Install if missing: `apt-get install tesseract-ocr tesseract-ocr-ara`

2. **Poor Search Results:**
   - Verify search_vector is populated
   - Check if content extraction succeeded
   - Review normalization quality
   - Adjust search rank threshold

3. **Slow Processing:**
   - Monitor Celery worker load
   - Check PDF file sizes
   - Review OCR necessity (many pages triggering OCR?)
   - Consider batch size adjustments

### Future Enhancements

**Potential Improvements:**
1. Multi-language OCR support
2. PDF page-level indexing
3. Advanced search filters (date range, page count, etc.)
4. Search result preview with page numbers
5. Export search results
6. Search analytics dashboard

---

## References

- [PostgreSQL Full-Text Search Documentation](https://www.postgresql.org/docs/current/textsearch.html)
- [Tesseract OCR Documentation](https://tesseract-ocr.github.io/)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)
- [Arabic Text Processing Best Practices](https://github.com/linuxscout)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-06  
**Authors:** Copilot AI Assistant, JoethonDev
