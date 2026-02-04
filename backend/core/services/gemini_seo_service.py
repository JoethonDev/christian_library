"""
Gemini AI Service for SEO Generation
Handles SEO metadata generation using Google Gemini API with Google-optimized prompts.
"""
import json
import logging
from typing import Dict, Tuple
from django.conf import settings
from google import genai

logger = logging.getLogger(__name__)


class GeminiSEOService:
    """Service for generating SEO metadata using Gemini AI"""
    
    def __init__(self):
        """Initialize Gemini client"""
        try:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")
                
            self.model = getattr(settings, 'GEMINI_MODEL', 'gemini-3-flash-preview')
            self.client = genai.Client(api_key=api_key)
            
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Gemini service is available"""
        return self.client is not None
    
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
                    "keywords": [...]
                },
                "ar": {
                    "meta_title": "...",
                    "description": "...",
                    "keywords": [...]
                }
            }
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create SEO prompt
            prompt = self._create_seo_prompt(content_type)
            
            # Generate content with Gemini
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, uploaded_file],
                config={
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "top_k": 20,
                    "response_mime_type": "application/json",
                    "response_schema": {
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
                                    }
                                },
                                "required": ["meta_title", "description", "keywords"]
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
                                    }
                                },
                                "required": ["meta_title", "description", "keywords"]
                            }
                        },
                        "required": ["en", "ar"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse and validate response
            seo_data = json.loads(response.text)
            cleaned_seo = self._validate_seo(seo_data)
            
            logger.info(f"Successfully generated SEO metadata for {content_type} file")
            return True, cleaned_seo
            
        except Exception as e:
            logger.error(f"Error generating SEO metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
    
    def _create_seo_prompt(self, content_type: str) -> str:
        """Create SEO generation prompt with Google optimization"""
        
        content_type_map = {
            'video': 'sermon, hymn, or teaching video',
            'audio': 'sermon, hymn, prayer, or teaching recording',
            'pdf': 'book, article, or teaching document'
        }
        
        content_description = content_type_map.get(content_type, 'content')
        
        return f"""You are creating SEO metadata for a {content_description} in the Christian Coptic Orthodox Church of Egypt library.

CONTEXT AND NICHE CONSTRAINT:
This content library exclusively serves the Christian Coptic Orthodox Church of Egypt community. All SEO metadata MUST:
- Focus on Coptic Orthodox theology, liturgy, saints, and traditions
- Target search queries from Egyptian Coptic Christians and those interested in Oriental Orthodox Christianity
- Use terminology specific to Coptic Orthodox practice (e.g., "Divine Liturgy", "Agpeya", "Coptic saints")
- Prioritize topical authority in Coptic Christian religious education

GOOGLE SEO REQUIREMENTS - STRICT CHARACTER LIMITS:
1. Meta Title: 50-60 characters MAXIMUM (critical for Google search display)
   - Must be compelling and include primary keyword
   - Front-load important words
   - Include "Coptic Orthodox" or "Coptic Christian" when relevant

2. Meta Description: 150-160 characters MAXIMUM (critical for Google snippet)
   - Must be action-oriented and engaging
   - Include primary and secondary keywords naturally
   - End with clear call-to-action or value proposition

3. Keywords: 8-12 high-value keywords per language
   - Mix of head terms (high volume) and long-tail phrases
   - Include Coptic Orthodox specific terms
   - Consider search intent (informational, educational, devotional)
   - Examples: "Coptic Orthodox liturgy", "St. Mark teachings", "Egyptian Christian prayers"

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
    "meta_title": "English meta title (50-60 chars)",
    "description": "English meta description (150-160 chars)",
    "keywords": ["keyword1", "keyword2", "..."]
  }},
  "ar": {{
    "meta_title": "Arabic meta title (50-60 chars)",
    "description": "Arabic meta description (150-160 chars)",
    "keywords": ["keyword1", "keyword2", "..."]
  }}
}}"""
    
    def _validate_seo(self, seo_data: Dict) -> Dict:
        """Validate and clean SEO metadata with character limit enforcement"""
        cleaned = {}
        
        for lang in ['en', 'ar']:
            if lang in seo_data:
                lang_data = seo_data[lang]
                
                # Enforce strict character limits
                meta_title = str(lang_data.get('meta_title', ''))[:60].strip()
                description = str(lang_data.get('description', ''))[:160].strip()
                
                # Validate and clean keywords
                keywords = lang_data.get('keywords', [])
                if isinstance(keywords, list):
                    keywords = [str(k)[:50].strip() for k in keywords[:12] if k]
                else:
                    keywords = []
                
                cleaned[lang] = {
                    'meta_title': meta_title,
                    'description': description,
                    'keywords': keywords
                }
            else:
                cleaned[lang] = {
                    'meta_title': '',
                    'description': '',
                    'keywords': []
                }
        
        return cleaned


def get_gemini_seo_service() -> GeminiSEOService:
    """Get or create Gemini SEO service singleton"""
    if not hasattr(get_gemini_seo_service, '_instance'):
        get_gemini_seo_service._instance = GeminiSEOService()
    return get_gemini_seo_service._instance
