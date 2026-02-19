# Gemini SEO Metadata Generation Upgrade

## Overview

The `gemini_services.py` has been upgraded to generate comprehensive SEO metadata for uploaded content (PDF, audio, video) while maintaining full backward compatibility with existing functionality.

## New Features

### 1. Full SEO Metadata Generation
- **Arabic & English SEO keywords** (up to 30 each)
- **SEO-optimized meta descriptions** (160 characters max)
- **Alternative SEO title suggestions** (3 alternatives)
- **Structured data with schema.org markup** (JSON-LD format)
- **Content-grounded keyword extraction**
- **Coptic Orthodox theological compliance**

### 2. Enhanced Metadata Fields

```json
{
  "title_ar": "string",
  "title_en": "string", 
  "description_ar": "string",
  "description_en": "string",
  "tags_ar": ["string"],           // Max 6 tags
  "tags_en": ["string"],           // Max 6 tags
  "seo_keywords_ar": ["string"],   // Max 30 keywords
  "seo_keywords_en": ["string"],   // Max 30 keywords
  "seo_meta_description_ar": "string",  // Max 160 chars
  "seo_meta_description_en": "string",  // Max 160 chars
  "seo_title_suggestions": ["string"],  // Max 3 titles
  "structured_data": {}            // JSON-LD schema.org
}
```

## API Methods

### New Method: `generate_seo_metadata()`
```python
def generate_seo_metadata(file_path: str, content_type: str) -> Tuple[bool, Dict]:
    """
    Generate comprehensive SEO metadata for uploaded file
    
    Args:
        file_path: Path to the uploaded file
        content_type: 'video', 'audio', or 'pdf'
        
    Returns:
        Tuple of (success: bool, metadata: dict)
    """
```

### Existing Method: `generate_content_metadata()` (Backward Compatible)
```python 
def generate_content_metadata(file_path: str, content_type: str) -> Tuple[bool, Dict[str, str]]:
    """
    Generate basic metadata (maintains backward compatibility)
    
    Returns: title_ar, title_en, description_ar, description_en, tags
    """
```

## Usage Examples

### 1. Generate Full SEO Metadata
```python
from apps.media_manager.services.gemini_service import get_gemini_service

service = get_gemini_service()
success, metadata = service.generate_seo_metadata('/path/to/file.pdf', 'pdf')

if success:
    # Access SEO fields
    arabic_keywords = metadata['seo_keywords_ar']      # Up to 30 keywords
    english_keywords = metadata['seo_keywords_en']     # Up to 30 keywords
    meta_desc_ar = metadata['seo_meta_description_ar'] # Max 160 chars
    meta_desc_en = metadata['seo_meta_description_en'] # Max 160 chars
    title_suggestions = metadata['seo_title_suggestions'] # 3 alternatives
    structured_data = metadata['structured_data']      # JSON-LD markup
```

### 2. Backward Compatible Usage
```python
# Existing code continues to work unchanged
service = get_gemini_service()
success, metadata = service.generate_content_metadata('/path/to/file.pdf', 'pdf')

if success:
    title_ar = metadata['title_ar']
    title_en = metadata['title_en']
    description_ar = metadata['description_ar']
    description_en = metadata['description_en']
    tags = metadata['tags']
```

## SEO Features

### 1. Content-Grounded Keywords
- **Primary extraction** (70%): Keywords directly from content
- **Safe expansion** (30%): Orthodox synonyms and variations
- **Theological safety**: Only Coptic Orthodox terminology
- **No generic terms**: Unless they appear in content

### 2. Meta Descriptions
- **Compelling summaries** under 160 characters
- **Primary keywords included** from content
- **Action-oriented language** where appropriate
- **Click-encouraging** while maintaining accuracy

### 3. Structured Data
- **Schema.org compliance** with appropriate types:
  - `Book` for PDF content
  - `VideoObject` for video content  
  - `AudioObject` for audio content
- **Rich metadata** for search engines
- **Coptic Orthodox attribution**

### 4. SEO Title Suggestions
- **3 alternative titles** (50-60 characters each)
- **Primary keywords included** from content
- **Search-optimized** phrasing
- **Theologically accurate** messaging

## Validation & Safety

### 1. Input Validation
- **String arrays**: Maximum lengths and item counts
- **Character limits**: Enforced for all text fields
- **JSON structure**: Validated structured data format
- **Required fields**: All schema fields validated

### 2. Theological Compliance
- **Coptic Orthodox terminology** exclusively
- **Content extraction first**: No imposed interpretations
- **Denominational constraints**: Prevents non-Orthodox terms
- **Source grounding**: Metadata must reflect actual content

### 3. SEO Best Practices
- **Keyword density**: Balanced extraction vs expansion
- **Character limits**: Google-recommended lengths
- **Schema markup**: Valid JSON-LD structure
- **Multilingual support**: Arabic and English optimization

## Technical Implementation

### 1. Enhanced Prompts
- **Extraction-first workflow**: Scan content before generating
- **SEO keyword rules**: 30 keywords per language with safe expansion
- **Schema.org integration**: Automated structured data generation
- **Quality controls**: Deterministic, low-variation outputs

### 2. Validation Pipeline
- **Multi-tier validation**: Field-specific and overall structure
- **Default fallbacks**: Safe defaults for all fields
- **Error handling**: Graceful degradation on failures
- **Type safety**: Comprehensive type checking

### 3. Performance Optimization
- **Single API call**: All metadata generated together
- **Efficient prompts**: Focused, structured instructions
- **Caching ready**: Deterministic outputs support caching
- **Resource cleanup**: Automatic file cleanup after processing

## Migration Notes

### Backward Compatibility
✅ **Existing code works unchanged**  
✅ **Same method signatures maintained**  
✅ **Original output format preserved**  
✅ **No breaking changes**

### New Integrations
- Add `generate_seo_metadata()` calls for new SEO features
- Update templates to use new SEO fields
- Integrate structured data into page headers
- Utilize alternative titles for A/B testing

## Testing

Run the test script to verify functionality:
```bash
cd /path/to/library_prod
python test_seo_metadata.py
```

The test script validates:
- Service availability
- Method signatures
- Expected output structure
- Backward compatibility

## Future Enhancements

1. **Caching layer** for repeated file analysis
2. **Batch processing** for multiple files
3. **Custom schema types** for specific content categories
4. **Advanced SEO analytics** integration
5. **A/B testing framework** for title optimization