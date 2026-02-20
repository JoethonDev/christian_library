# Admin Dashboard Document Upload Integration

## Overview
This implementation adds supplementary Word document upload capability to the admin dashboard upload form. When a document is provided during upload, its text content is extracted and used for `book_content` instead of OCR, applying to all content types (video, audio, PDF).

## Key Requirements Met

### 1. Document Upload Integration
✅ Both admin dashboard endpoints support document uploads:
- `path('dashboard/upload/', admin_views.upload_content, name='upload_content')`
- `path('dashboard/upload/handle/', admin_views.handle_content_upload, name='handle_upload')`

### 2. Book Content for All Item Types
✅ Document text is used for `book_content` field regardless of content type:
- Videos can have supplementary document content
- Audio files can have supplementary document content
- PDFs can have supplementary document content

### 3. OCR Bypass for PDFs with Documents
✅ When a document is provided with a PDF:
- Document text is extracted and set as `book_content`
- PDF OCR extraction is skipped automatically
- Saves processing time and resources

## Implementation Details

### 1. Template Changes (`upload_content.html`)
Added new section for supplementary document upload:
```html
<!-- Supplementary Document Upload (Optional) -->
<div class="mb-5">
    <label>Supplementary Document (Optional)</label>
    <p>Upload a Word document (.doc/.docx) with book content. 
       This text will be used for search indexing instead of OCR.</p>
    
    <div class="upload-zone">
        <input type="file" id="document-input" name="document" 
               accept=".doc,.docx" onchange="updateDocumentFileName(this)">
        <i class="bi bi-file-earmark-word"></i>
        <p>Click to upload document</p>
        <p>Supported: .doc, .docx (Max 2GB)</p>
    </div>
</div>
```

**JavaScript Functions Added:**
- `updateDocumentFileName()` - Shows selected document name
- `clearDocument()` - Removes selected document

### 2. Admin View Changes (`admin_views.py`)
Updated `handle_content_upload()` to extract and pass document file:
```python
def handle_content_upload(request):
    # ... existing code ...
    
    # Get document file if provided
    document_file = request.FILES.get('document')
    
    # Create content item with document
    result = upload_service.create_content_item(
        file_obj=file_obj,
        # ... other parameters ...
        document_file=document_file  # Pass document file
    )
```

### 3. Upload Service Changes (`upload_service.py`)
Modified `create_content_item()` to process documents:

**Key Logic:**
1. Accept `document_file` parameter
2. If document provided:
   - Validate document (file type, size)
   - Extract text synchronously using DocumentProcessorService
   - Save to temporary file for processing
   - Clean up temporary file
3. Create content item as normal
4. After successful creation:
   - Set `book_content` from extracted document text
   - Update `search_vector` immediately
   - Save changes atomically

```python
def create_content_item(
    self,
    file_obj,
    # ... other parameters ...
    document_file = None  # New parameter
):
    # Extract text from document if provided
    book_content_from_doc = None
    if document_file:
        doc_processor = DocumentProcessorService()
        # Validate and extract text
        book_content_from_doc = doc_processor.extract_text_from_document(...)
    
    # Create content item (video/audio/pdf)
    success, message, content_item = self.upload_xxx(...)
    
    # Set book_content from document
    if success and book_content_from_doc:
        content_item.book_content = book_content_from_doc
        content_item.save(update_fields=['book_content'])
        content_item.update_search_vector()
        content_item.save(update_fields=['search_vector'])
```

### 4. Model Changes (`models.py`)
Updated `extract_text_from_pdf()` to skip OCR when book_content exists:

```python
def extract_text_from_pdf(self):
    """
    Extract text from PDF. Skips if book_content already populated.
    """
    # Skip extraction if book_content already exists
    if self.book_content and self.book_content.strip():
        logger.info(f"Skipping PDF extraction - book_content already populated from document")
        return
    
    # Proceed with normal PDF extraction/OCR
    self.book_content = processor.extract_text_from_pdf(pdf_path, page_count)
```

## Workflow Diagrams

### Upload Flow with Document

```
User uploads file + document
         ↓
Admin Dashboard (upload_content.html)
         ↓
handle_content_upload() receives both files
         ↓
MediaUploadService.create_content_item()
         ↓
    ┌────────────────────┐
    │ Document provided? │
    └────────┬───────────┘
             │ Yes
             ↓
    Extract text synchronously
             ↓
    Create ContentItem (video/audio/pdf)
             ↓
    Set book_content = document_text
             ↓
    Update search_vector
             ↓
    Save to database
```

### PDF Processing with Document

```
PDF ContentItem created with book_content from document
         ↓
Background task: extract_and_index_contentitem()
         ↓
Calls: extract_text_from_pdf()
         ↓
    ┌──────────────────────┐
    │ book_content exists? │
    └─────────┬────────────┘
              │ Yes
              ↓
    Skip OCR - log and return
              
    (OCR never runs, saves time/resources)
```

## Benefits

### 1. Better Content Quality
- Users can provide high-quality transcribed/typed content
- Avoids OCR errors and inaccuracies
- Supports proper formatting and structure

### 2. Performance Improvement
- For PDFs with documents: no OCR processing needed
- Faster upload completion
- Reduced server load

### 3. Flexibility
- Works with all content types (not just PDFs)
- Videos and audio can have searchable book content
- Optional - doesn't break existing uploads

### 4. Search Enhancement
- Document content is immediately indexed
- No waiting for background OCR tasks
- Better search results from quality content

## Testing

### Test Cases Added:
1. `test_create_content_item_with_document()` - Verifies document file is processed
2. `test_pdf_extraction_skips_when_book_content_exists()` - Verifies OCR bypass

### Manual Testing Scenarios:
1. **Video + Document**: Upload video with .docx → book_content populated
2. **Audio + Document**: Upload audio with .doc → book_content populated
3. **PDF + Document**: Upload PDF with .docx → book_content from document, OCR skipped
4. **PDF without Document**: Upload PDF alone → OCR runs normally
5. **Invalid Document**: Upload with .txt → validation error
6. **No Document**: Upload without document → existing flow works

## Files Modified

1. `backend/templates/admin/upload_content.html` - Added document upload UI
2. `backend/apps/frontend_api/admin_views.py` - Updated to handle document file
3. `backend/apps/media_manager/services/upload_service.py` - Process document and set book_content
4. `backend/apps/media_manager/models.py` - Skip OCR when book_content exists
5. `backend/apps/media_manager/test_document_support.py` - Added tests

## Usage Instructions

### For Administrators:

1. **Navigate to Upload Page**
   - Go to Dashboard → Upload Content

2. **Select Content Type**
   - Choose Video, Audio, or PDF

3. **Upload Main File**
   - Click upload zone or drag-drop main media file

4. **Optional: Upload Document**
   - Click the "Supplementary Document" section
   - Select a .doc or .docx file
   - File name will display with remove button

5. **Fill in Details**
   - Enter title, description, tags
   - Optional: Add SEO metadata

6. **Submit**
   - Click "Upload Content"
   - Document text will be extracted and used for book_content
   - For PDFs: OCR will be skipped automatically

### Example Use Cases:

**Case 1: Church Sermon Video with Transcript**
- Upload video file
- Upload .docx transcript as document
- Transcript becomes searchable book_content

**Case 2: Hymn Audio with Lyrics**
- Upload audio file
- Upload .doc with hymn lyrics
- Lyrics become searchable book_content

**Case 3: PDF Book with Typed Content**
- Upload scanned PDF
- Upload .docx with typed/corrected text
- Typed text used instead of OCR
- Better quality, faster processing

## Technical Notes

### Synchronous vs Asynchronous Processing
- Document extraction is **synchronous** during upload
- Ensures book_content is set before media processing begins
- Prevents race conditions with PDF OCR task

### Transaction Safety
- book_content update uses `transaction.atomic()`
- search_vector updated immediately after
- Changes are atomic and consistent

### Error Handling
- Document validation errors are logged but don't block upload
- If document extraction fails, content still uploads
- User gets successful upload even if document processing fails

### Memory Management
- Document files saved to temporary location
- Text extracted from temp file
- Temp file cleaned up after extraction
- No permanent storage of document file itself

## Future Enhancements

Potential improvements (not currently implemented):

1. **Document Storage**: Save the document file itself for later download
2. **Progress Indicator**: Show document extraction progress
3. **Preview**: Show extracted text before submission
4. **Edit Option**: Allow editing extracted text before saving
5. **Multiple Documents**: Support multiple document files per content item
6. **Auto-detection**: Automatically detect document language

## Conclusion

This implementation successfully integrates supplementary Word document upload into the admin dashboard, with the extracted text used for `book_content` across all content types. For PDFs, when a document is provided, OCR is intelligently bypassed, saving processing time and improving content quality.

The solution is:
- ✅ Backward compatible (optional document, existing flow unchanged)
- ✅ Performant (synchronous extraction, OCR bypass)
- ✅ Flexible (works with all content types)
- ✅ User-friendly (simple UI, clear workflow)
- ✅ Tested (unit tests for key functionality)
