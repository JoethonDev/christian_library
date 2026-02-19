"""
Gemini AI Service for SEO Generation
Handles SEO metadata generation using Google Gemini API with Google-optimized prompts.
Uses Gemini 3 Flash for highest quality SEO generation.
"""
import logging
from typing import Dict, Tuple
from .gemini_base_service import BaseGeminiService

logger = logging.getLogger(__name__)


class GeminiSEOService(BaseGeminiService):
    """Service for generating SEO metadata using Gemini 3 Flash"""
    
    def __init__(self):
        """Initialize with Gemini 3 Flash as default model"""
        super().__init__(default_model=self.MODEL_3_FLASH)
    
    def generate_seo(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate SEO metadata for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, seo_data: dict)
            SEO data follows standardized JSON format:
            {
                "en": {
                    "meta_title": "...",
                    "description": "...",
                    "keywords": [...],
                    "structured_data": {...}
                },
                "ar": {
                    "meta_title": "...",
                    "description": "...",
                    "keywords": [...],
                    "structured_data": {...}
                }
            }
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self._upload_file(file_path)
            
            # Create SEO prompt
            prompt = self._create_seo_prompt(content_type)
            
            # Define response schema with structured data
            response_schema = {
                "type": "object",
                "properties": {
                    "en": {
                        "type": "object",
                        "properties": {
                            "meta_title": {"type": "string"},
                            "description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"}
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["meta_title", "description", "keywords", "structured_data"]
                    },
                    "ar": {
                        "type": "object",
                        "properties": {
                            "meta_title": {"type": "string"},
                            "description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"}
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["meta_title", "description", "keywords", "structured_data"]
                    },
                    "transcript": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["en", "ar", "transcript", "notes"]
            }
            
            # Generate content with Gemini
            seo_data = self._generate_content(prompt, uploaded_file, response_schema)
            
            # Clean up uploaded file
            self._cleanup_file(uploaded_file)
            
            # Validate and clean response
            cleaned_seo = self._validate_seo(seo_data)
            
            logger.info(f"Successfully generated SEO metadata for {content_type} file")
            return True, cleaned_seo
            
        except Exception as e:
            logger.error(f"Error generating SEO metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
    
    def _create_seo_prompt(self, content_type: str) -> str:
        """
        Create SEO generation prompt with Google optimization.
        
        Phase 2 Enhancement: Includes concrete examples and strict character enforcement.
        Reference: https://developers.google.com/search/docs/fundamentals/seo-starter-guide
        """
        
        content_type_map = {
            'video': 'sermon, hymn, or teaching video',
            'audio': 'sermon, hymn, prayer, or teaching recording',
            'pdf': 'book, article, or teaching document'
        }
        
        # Media type for title formatting (Phase 1 requirement)
        media_type_map = {
            'video': {'en': 'Video', 'ar': 'فيديو'},
            'audio': {'en': 'Audio', 'ar': 'صوت'},
            'pdf': {'en': 'PDF Book', 'ar': 'كتاب PDF'}
        }
        
        content_description = content_type_map.get(content_type, 'content')
        media_type_en = media_type_map.get(content_type, {}).get('en', 'Content')
        media_type_ar = media_type_map.get(content_type, {}).get('ar', 'محتوى')
        
        return f"""You are creating SEO metadata for a {content_description} in the Christian Coptic Orthodox Church of Egypt library.

CONTEXT AND NICHE CONSTRAINT:
This content library exclusively serves the Christian Coptic Orthodox Church of Egypt community. All SEO metadata MUST:
- Focus on Coptic Orthodox theology, liturgy, saints, and traditions
- Target search queries from Egyptian Coptic Christians and those interested in Oriental Orthodox Christianity
- Use terminology specific to Coptic Orthodox practice (e.g., "Divine Liturgy", "Agpeya", "Coptic saints")
- Prioritize topical authority in Coptic Christian religious education

GOOGLE SEO REQUIREMENTS - STRICT CHARACTER LIMITS:

1. Meta Title: EXACTLY 50-60 characters (Google displays ~60 chars max)
   
   REQUIRED FORMAT: "{{Content Title}} | {media_type_en} | Anba Abraam Library"
   - If content title is too long, truncate it to fit the format
   - Front-load important words
   - Include primary keyword in content title portion
   
   ✅ EXCELLENT EXAMPLES (Study These):
   
   EN (58 chars): "Divine Liturgy Explained | Video | Anba Abraam Library"
   AR (54 chars): "شرح القداس الإلهي | فيديو | مكتبة الأنبا أبرآم"
   
   EN (59 chars): "Prayer of Agpeya Guide | Audio | Anba Abraam Library"
   AR (56 chars): "دليل صلاة الأجبية | صوت | مكتبة الأنبا أبرآم"
   
   ❌ BAD EXAMPLES (Never Do This):
   
   "Anba Abraam teaches about Divine Liturgy in video" (too long - 72 chars, missing format)
   "Divine Liturgy" (too short - 14 chars, missing media type and site)
   "Divine Liturgy - Video - Christian Library" (wrong separator, wrong site name)

2. Meta Description: EXACTLY 150-160 characters (Google displays ~155-160 chars)
   
   REQUIRED FORMULA: {{Action}} "{{Title}}" by Bishop Anba Abraam. {{Value Prop}}. Free {{media_type}}.
   
   Where:
   - Action = Watch/Listen/Download (based on media type)
   - Value Prop = "The largest official collection of Coptic Orthodox teachings" or similar
   
   ✅ EXCELLENT EXAMPLES:
   
   EN (158 chars): "Watch 'Divine Liturgy Explained' by Bishop Anba Abraam. The largest official collection of Coptic Orthodox teachings. Free spiritual videos."
   
   AR (159 chars): "شاهد 'شرح القداس الإلهي' للأنبا أبرآم. أكبر مجموعة رسمية لتعاليم الكنيسة القبطية الأرثوذكسية. فيديوهات روحية مجانية."
   
   EN (157 chars): "Listen to 'Prayer of Agpeya Guide' by Bishop Anba Abraam. Access authentic Coptic Orthodox spiritual content. Free audio recordings."
   
   ❌ BAD EXAMPLES:
   
   "A video about Divine Liturgy" (too short - 28 chars, no author, no value)
   "This comprehensive video lecture series explores the deep theological and historical significance of the Divine Liturgy in the Coptic Orthodox tradition, presented by His Grace Bishop Anba Abraam" (way too long - 195 chars)
   "Divine Liturgy video by Anba Abraam" (too short, missing value proposition)

3. Keywords: 8-12 high-value keywords per language
   - Mix of head terms (high volume) and long-tail phrases
   - Include Coptic Orthodox specific terms
   - Consider search intent (informational, educational, devotional)
   
   Examples:
   EN: "Coptic Orthodox liturgy", "Divine Liturgy explained", "St. Mark teachings", "Egyptian Christian prayers", "Coptic saints", "Anba Abraam sermons"
   AR: "القداس الإلهي", "الكنيسة القبطية", "تعاليم الأنبا أبرآم", "صلوات قبطية", "الأرثوذكسية القبطية"

4. Structured Data (JSON-LD): Generate Schema.org markup for rich results
   - Use @type: "VideoObject" for videos, "AudioObject" for audio, "Article" or "Book" for PDFs
   - Include name, description, and inLanguage
   - Ensure valid Schema.org format for Google rich results

CHARACTER COUNT VALIDATION - CRITICAL:
- Count every character including spaces
- EN meta_title: Must be 50-60 chars (not 49, not 61)
- AR meta_title: Must be 50-60 chars
- EN description: Must be 150-160 chars (not 149, not 161)
- AR description: Must be 150-160 chars
- If you generate 61 chars, Google will truncate with "..." - this looks unprofessional
- If you generate 149 chars, you're wasting valuable search result space

MEDIA TYPE FOR THIS CONTENT: {media_type_en} (EN) / {media_type_ar} (AR)
Use these exact strings in the title format.

KEYWORD STRATEGY:
- Prioritize keywords with high search volume in Coptic Orthodox context
- Use natural language that matches how people search
- Include Arabic transliterations where appropriate (e.g., "Agpeya", "Tasbeha")
- Consider both local (Egypt) and diaspora (US, Canada, Australia) search patterns

THEOLOGICAL ACCURACY:
- Ensure all SEO content reflects accurate Coptic Orthodox theology
- Reference specific liturgical seasons, feasts, or saints when applicable
- Use proper Coptic Orthodox terminology

Return SEO metadata in the following JSON format:
{{
  "en": {{
    "meta_title": "Content Title | {media_type_en} | Anba Abraam Library",
    "description": "Action 'Title' by Bishop Anba Abraam. Value proposition. Free {media_type_en.lower()}.",
    "keywords": ["keyword1", "keyword2", "...", "keyword8-12"],
    "structured_data": {{
      "@context": "https://schema.org",
      "@type": "VideoObject",
      "name": "Title",
      "description": "Description",
      "inLanguage": "en"
    }}
  }},
  "ar": {{
    "meta_title": "عنوان المحتوى | {media_type_ar} | مكتبة الأنبا أبرآم",
    "description": "فعل 'العنوان' للأنبا أبرآم. القيمة المضافة. {media_type_ar} مجاني.",
    "keywords": ["كلمة1", "كلمة2", "...", "كلمة8-12"],
    "structured_data": {{
      "@context": "https://schema.org",
      "@type": "VideoObject",
      "name": "العنوان",
      "description": "الوصف",
      "inLanguage": "ar"
    }}
  }},
  "transcript": "Full transcript or detailed content summary (Arabic)",
  "notes": "Contextual study notes and historical background (Arabic)"
}}

FINAL REMINDER: Count your characters carefully. 50-60 for titles, 150-160 for descriptions. No exceptions."""
    
    def _validate_seo(self, seo_data: Dict) -> Dict:
        """
        Validate and clean SEO metadata with strict character limit enforcement.
        
        Phase 2 Enhancement: Adds warning logs for quality control and debugging.
        Enforces Google's best practices for title and description lengths.
        """
        cleaned = {
            'transcript': str(seo_data.get('transcript', '')).strip(),
            'notes': str(seo_data.get('notes', '')).strip()
        }
        
        for lang in ['en', 'ar']:
            if lang in seo_data:
                lang_data = seo_data[lang]
                
                # Validate meta_title with strict length checking
                meta_title = str(lang_data.get('meta_title', '')).strip()
                title_len = len(meta_title)
                
                if title_len > 60:
                    logger.warning(
                        f"[{lang.upper()}] Meta title TOO LONG ({title_len} chars, max 60): "
                        f"{meta_title[:70]}..."
                    )
                    meta_title = meta_title[:60]  # Hard truncate
                elif title_len < 50:
                    logger.warning(
                        f"[{lang.upper()}] Meta title TOO SHORT ({title_len} chars, min 50): "
                        f"{meta_title}"
                    )
                elif 50 <= title_len <= 60:
                    logger.info(
                        f"[{lang.upper()}] ✓ Meta title perfect length ({title_len} chars): "
                        f"{meta_title}"
                    )
                
                # Validate description with strict length checking
                description = str(lang_data.get('description', '')).strip()
                desc_len = len(description)
                
                if desc_len > 160:
                    logger.warning(
                        f"[{lang.upper()}] Description TOO LONG ({desc_len} chars, max 160): "
                        f"{description[:70]}..."
                    )
                    description = description[:160]  # Hard truncate
                elif desc_len < 150:
                    logger.warning(
                        f"[{lang.upper()}] Description TOO SHORT ({desc_len} chars, min 150): "
                        f"{description[:70]}..."
                    )
                elif 150 <= desc_len <= 160:
                    logger.info(
                        f"[{lang.upper()}] ✓ Description perfect length ({desc_len} chars)"
                    )
                
                # Validate and clean keywords
                keywords = lang_data.get('keywords', [])
                if isinstance(keywords, list):
                    # Limit to 12 keywords, each max 50 chars
                    keywords = [str(k)[:50].strip() for k in keywords[:12] if k]
                    keyword_count = len(keywords)
                    
                    if keyword_count < 8:
                        logger.warning(
                            f"[{lang.upper()}] Too few keywords ({keyword_count}, target 8-12)"
                        )
                    elif keyword_count > 12:
                        logger.warning(
                            f"[{lang.upper()}] Too many keywords ({keyword_count}, truncated to 12)"
                        )
                    else:
                        logger.info(
                            f"[{lang.upper()}] ✓ Keyword count optimal ({keyword_count} keywords)"
                        )
                else:
                    logger.error(f"[{lang.upper()}] Keywords not a list, defaulting to empty")
                    keywords = []
                
                # Validate structured data
                structured_data = lang_data.get('structured_data', {})
                if not isinstance(structured_data, dict):
                    logger.error(f"[{lang.upper()}] Structured data not a dict, defaulting to empty")
                    structured_data = {}
                elif '@type' not in structured_data:
                    logger.warning(f"[{lang.upper()}] Structured data missing @type")
                else:
                    logger.info(
                        f"[{lang.upper()}] ✓ Structured data present (@type: {structured_data.get('@type')})"
                    )
                
                cleaned[lang] = {
                    'meta_title': meta_title,
                    'description': description,
                    'keywords': keywords,
                    'structured_data': structured_data
                }
            else:
                logger.error(f"[{lang.upper()}] Language data missing from SEO response")
                cleaned[lang] = {
                    'meta_title': '',
                    'description': '',
                    'keywords': [],
                    'structured_data': {}
                }
        
        return cleaned


def get_gemini_seo_service() -> GeminiSEOService:
    """Get or create Gemini SEO service singleton"""
    if not hasattr(get_gemini_seo_service, '_instance'):
        get_gemini_seo_service._instance = GeminiSEOService()
    return get_gemini_seo_service._instance
