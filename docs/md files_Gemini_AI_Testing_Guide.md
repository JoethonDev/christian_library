# Gemini AI Integration Testing Guide

## Overview
This document provides testing instructions for the Gemini AI content generation feature implemented for **Coptic Orthodox Christian content** in the admin dashboard.

## Components Implemented

### 1. Backend Components
- ✅ **Gemini Service** ([media_manager/services/gemini_service.py](media_manager/services/gemini_service.py))
  - File upload to Gemini Files API
  - Structured prompt generation for different content types
  - JSON response parsing and validation
  - Error handling and cleanup

- ✅ **Django Settings** ([config/settings/base.py](config/settings/base.py))
  - GEMINI_API_KEY environment variable configuration

- ✅ **Admin Views** ([frontend_api/admin_views.py](frontend_api/admin_views.py))
  - `generate_content_metadata` endpoint
  - File validation and temporary storage
  - AI service integration and response handling

- ✅ **URL Configuration** ([frontend_api/urls.py](frontend_api/urls.py))
  - `/admin/upload/generate/` endpoint for AI generation

### 2. Frontend Components  
- ✅ **Upload Form** ([templates/admin/upload_content.html](templates/admin/upload_content.html))
  - "Generate with AI" button with gradient styling
  - JavaScript for AI generation requests
  - Form field population with AI results
  - Success/error alert handling

## Testing Instructions

### Prerequisites
1. Set the `GEMINI_API_KEY` environment variable with your Google Gemini API key
2. Optionally set `GEMINI_MODEL` (defaults to `gemini-2.5-flash` - optimal for accuracy, speed, and multilingual support)
3. Ensure all dependencies are installed from requirements/base.txt
4. Start the Django development server

### Test Cases

#### Test Case 1: Video File Generation
1. Navigate to `/admin/upload/`
2. Select "Video" content type
3. Choose a `.mp4`, `.avi`, or `.mov` file
4. Click "Generate with AI"
5. Verify form fields are populated with:
   - Arabic and English titles
   - Arabic and English descriptions
   - Relevant Arabic tags

#### Test Case 2: Audio File Generation  
1. Select "Audio" content type
2. Choose a `.mp3`, `.wav`, or `.flac` file
3. Click "Generate with AI"
4. Verify metadata generation for audio content

#### Test Case 3: PDF File Generation
1. Select "Document" content type  
2. Choose a `.pdf` file
3. Click "Generate with AI"
4. Verify metadata generation for document content

#### Test Case 4: Error Handling
1. Try generating without selecting a file (should show alert)
2. Try generating without selecting content type (should show alert)
3. Try with invalid file type (should show validation error)
4. Test with network disconnected (should show network error)

### Expected Behavior

#### Success Response
```javascript
{
  "success": true,
  "metadata": {
    "title_ar": "عنوان بالعربية",
    "title_en": "English Title", 
    "description_ar": "وصف مفصل بالعربية...",
    "description_en": "Detailed English description...",
    "tags": ["تعليم مسيحي", "الكتاب المقدس", "عبادة"]
  }
}
```

#### Error Response
```javascript
{
  "success": false,
  "error": "Error message"
}
```

### UI Elements

#### Generate Button States
- **Default**: Purple gradient button with sparkles icon
- **Loading**: "Generating..." with hourglass icon, disabled
- **Success**: Green alert with checkmark icon
- **Error**: Yellow/red alert with appropriate icon

#### Form Field Population
- Fields are automatically filled with AI-generated content
- Arabic fields use RTL text direction
- English fields use LTR text direction
- Tags are comma-separated

## Troubleshooting

### Common Issues
1. **API Key Missing**: Set GEMINI_API_KEY environment variable
2. **Service Unavailable**: Check internet connection and API key validity
3. **File Upload Fails**: Verify file size limits and supported formats
4. **Slow Response**: Large files may take longer to process

### Debug Information
- Check Django logs for Gemini service errors
- Use browser developer tools to inspect network requests
- Verify CSRF token is included in AI generation requests

## Integration Notes

### File Type Support
- **Video**: .mp4, .avi, .mov, .mkv, .wmv  
- **Audio**: .mp3, .wav, .flac, .aac, .ogg
- **PDF**: .pdf only

### Content Generation
- Titles: 3-6 words, source-grounded using actual content terms
- Descriptions: 140-160 words, factual extraction from content vocabulary
- Tags: Exactly 5-6 Arabic tags derived from repeated keywords/explicit themes
- Denominational Constraint: Coptic Orthodox terminology only
- Source Grounding: No inference or invention, only explicit content extraction
- Output Consistency: Enhanced with temperature=0.1, top_p=0.9, top_k=20

### Security Considerations
- Temporary files are cleaned up after processing
- API key is stored as environment variable
- File uploads are validated before AI processing
- CSRF protection on all endpoints

## Next Steps
- Monitor AI generation quality and adjust prompts if needed
- Consider adding batch processing for multiple files
- Implement content quality scoring and feedback
- Add support for additional file formats as needed