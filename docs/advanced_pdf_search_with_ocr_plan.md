# Advanced PDF Search with OCR: Implementation Plan

This document outlines the detailed plan for implementing advanced search functionality within PDF content using OCR. The goal is to enable users to search for text inside scanned or image-based PDFs, with support for both Arabic and English languages. The implementation will focus on high accuracy and performance for large PDFs.

---

## Objectives

1. **OCR Integration:** Extract text from scanned or image-based PDFs using OCR.
2. **Normalization:** Normalize the extracted text by removing non-Arabic characters and applying text cleaning rules.
3. **Indexing:** Index the extracted text for full-text search.
4. **Search Functionality:** Enable search queries in both Arabic and English within the extracted PDF content.
5. **UI Update:** Update the user interface to allow searching within PDF content.
6. **Performance Optimization:** Ensure high accuracy and performance for large PDFs.

---

## Implementation Steps

### 1. OCR Processing for PDFs

- **Objective:** Extract text from scanned or image-based PDFs.
- **Steps:**
  1. Use the `ocr_pdf` function from `fined_ocr.py` to process uploaded PDFs.
  2. Convert each page of the PDF to an image using `pdf2image.convert_from_path`.
  3. Preprocess the image using `preprocess_image` to enhance OCR accuracy.
  4. Use `pytesseract.image_to_string` with Arabic language configuration (`lang="ara"`) to extract text from the processed image.
  5. Save the extracted text to a file for further processing.

### 2. Text Normalization

- **Objective:** Normalize the extracted text to improve search accuracy.
- **Steps:**
  1. Use the `normalize_text` function from `fined_ocr.py`.
  2. Modify the normalization logic to remove all characters except Arabic characters and spaces.
     - Use the regex pattern `[^\u0600-\u06FF\s]` to match non-Arabic characters and replace them with an empty string.
  3. Apply additional normalization rules, such as replacing Arabic diacritics and normalizing specific characters (e.g., `أ` to `ا`).
  4. Save the normalized text to a file for indexing.

### 3. Indexing Extracted Text

- **Objective:** Index the normalized text for full-text search.
- **Steps:**
  1. Use a search engine like Elasticsearch or a Django-compatible library like `django-haystack`.
  2. Create a new model `PDFContentIndex` to store the indexed text.
     ```python
     from django.db import models

     class PDFContentIndex(models.Model):
         pdf = models.OneToOneField('media_manager.PdfMeta', on_delete=models.CASCADE, related_name='content_index')
         content = models.TextField()
         created_at = models.DateTimeField(auto_now_add=True)
         updated_at = models.DateTimeField(auto_now=True)
     ```
  3. Write a management command or Celery task to process and index the text for all existing PDFs.
  4. Ensure the indexed text is searchable using the search engine.

### 4. Search Functionality

- **Objective:** Enable users to search for text within PDF content.
- **Steps:**
  1. Add a search endpoint in the `media_manager` app to handle search queries.
     ```python
     from django.http import JsonResponse
     from django.db.models import Q
     from .models import PDFContentIndex

     def search_pdf_content(request):
         query = request.GET.get('q', '').strip()
         if not query:
             return JsonResponse({'error': 'Query parameter is required'}, status=400)

         results = PDFContentIndex.objects.filter(
             Q(content__icontains=query)
         ).values('pdf__id', 'pdf__title', 'content')

         return JsonResponse({'results': list(results)})
     ```
  2. Update the frontend to include a search bar for PDF content.
  3. Display search results with highlighted matches.

### 5. UI Update

- **Objective:** Update the user interface to allow searching within PDF content.
- **Steps:**
  1. Add a search bar to the PDF management page in the admin UI.
  2. Use JavaScript (e.g., Alpine.js) to handle search input and display results dynamically.
  3. Implement pagination for large search results.

### 6. Performance Optimization

- **Objective:** Ensure high accuracy and performance for large PDFs.
- **Steps:**
  1. Optimize OCR preprocessing to handle large PDFs efficiently.
  2. Use batch processing for indexing large amounts of text.
  3. Cache search results to reduce database queries for repeated searches.
  4. Monitor and log performance metrics to identify bottlenecks.

---

## Code Integration

The following code from `fined_ocr.py` will be used and modified as needed:

### OCR Processing
```python
def ocr_pdf(pdf_path):
    start = now()
    full_text = []

    page_count = 0
    for page in convert_from_path(pdf_path, dpi=DPI):
        page_count += 1
        processed = preprocess_image(page)
        text = pytesseract.image_to_string(
            processed, lang="ara", config="--psm 6"
        )
        full_text.append(text)

    return {
        "text": "\n".join(full_text),
        "pages": page_count,
        "time": elapsed(start),
    }
```

### Text Normalization
```python
ARABIC_NORMALIZATION = {
    "أ": "ا", "إ": "ا", "آ": "ا",
    "ى": "ي", "ة": "ه",
    "ؤ": "و", "ئ": "ي",
}

def normalize_text(text):
    start = now()

    # Remove non-Arabic characters
    text = re.sub(r"[^\u0600-\u06FF\s]", "", text)

    for k, v in ARABIC_NORMALIZATION.items():
        text = text.replace(k, v)

    text = re.sub(r"[.:]{2,}", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip(), elapsed(start)
```

---

## Deliverables

1. **Backend:**
   - Updated `fined_ocr.py` with modified normalization logic.
   - New `PDFContentIndex` model for storing indexed text.
   - Search endpoint for querying indexed PDF content.

2. **Frontend:**
   - Search bar and results display for PDF content.
   - Pagination and highlighting for search results.

3. **Documentation:**
   - Update relevant documentation to include details about the new feature.
   - Provide usage instructions for the search functionality.

4. **Testing:**
   - Unit tests for OCR processing, normalization, and search functionality.
   - Integration tests for the search endpoint and UI.

---

## Timeline

| Task                          | Estimated Time |
|-------------------------------|----------------|
| OCR Integration               | 2 days         |
| Normalization Implementation  | 1 day          |
| Indexing Setup                | 2 days         |
| Search Endpoint Development   | 1 day          |
| UI Update                     | 2 days         |
| Performance Optimization      | 2 days         |
| Testing                       | 2 days         |
| **Total**                     | **10 days**    |

---

This plan provides a comprehensive approach to implementing advanced PDF search with OCR functionality, ensuring high accuracy and performance for large PDFs.