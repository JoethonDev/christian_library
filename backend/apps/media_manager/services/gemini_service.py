"""
Gemini AI Service for Content Generation
Handles file upload and AI-powered content generation using Google Gemini API
"""
import os
import tempfile
import logging
from typing import Dict, Optional, Tuple
from django.conf import settings
from google import genai

logger = logging.getLogger(__name__)


class GeminiContentGenerator:
    """Service for generating content metadata using Gemini AI"""
    
    def __init__(self):
        """Initialize Gemini client"""
        try:
            # Get API key from settings
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")
                
            # Get model from settings with optimal default
            # gemini-2.5-flash: Best price-performance, large-scale processing, multilingual, fast response
            self.model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
                
            # Initialize client with API key
            self.client = genai.Client(api_key=api_key)
            
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Gemini service is available"""
        return self.client is not None
    
    def generate_content_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict[str, str]]:
        """
        Generate metadata for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
            metadata contains: title_ar, title_en, description_ar, description_en, tags
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create prompt based on content type
            prompt = self._create_prompt(content_type)
            
            # Generate content with Gemini using consistency-optimized config
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, uploaded_file],
                generation_config={
                    "temperature": 0.1,  # Low temperature for deterministic outputs
                    "top_p": 0.9,       # Nucleus sampling for consistency
                    "top_k": 20,        # Limit token choices for predictability
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "title_ar": {"type": "string"},
                            "title_en": {"type": "string"},
                            "description_ar": {"type": "string"},
                            "description_en": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["title_ar", "title_en", "description_ar", "description_en", "tags"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse response
            import json
            metadata = json.loads(response.text)
            
            # Validate and clean metadata
            cleaned_metadata = self._validate_metadata(metadata)
            
            logger.info(f"Successfully generated metadata for {content_type} file")
            return True, cleaned_metadata
            
        except Exception as e:
            logger.error(f"Error generating content metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
    
    def _create_prompt(self, content_type: str) -> str:
        """Create appropriate prompt based on content type"""
        
        content_type_map = {
            'video': 'فيديو (video)',
            'audio': 'تسجيل صوتي (audio recording)', 
            'pdf': 'كتاب أو وثيقة (book or document)'
        }
        
        content_desc = content_type_map.get(content_type, 'محتوى (content)')
        
        prompt = f"""
You are a senior librarian, theologian, and content analyst specialized in the
Coptic Orthodox Church of Egypt.

ALL content belongs strictly to the Coptic Orthodox Christian tradition in Egypt.

────────────────────────────────────────
ABSOLUTE SOURCE-GROUNDING RULE (MANDATORY)
────────────────────────────────────────
ALL generated metadata MUST be grounded primarily in the actual words,
phrases, and themes found in the uploaded content file.

You MUST:
- First identify key terms, repeated phrases, and explicit topics from the content.
- Use those extracted terms as the primary vocabulary source.
- Prefer wording that clearly appears in the file itself.

You MUST NOT:
- Introduce new theological concepts not explicitly present.
- Normalize the content into common church topics.
- Enrich or "improve" meaning beyond what exists in the file.

If a term or concept does not appear clearly in the content, DO NOT use it.

────────────────────────────────────────
DENOMINATIONAL CONSTRAINT (MANDATORY)
────────────────────────────────────────
Use ONLY terminology accepted by the Coptic Orthodox Church of Egypt.

You MUST:
- Use Arabic Orthodox terminology commonly used in Egypt.
- Ensure all wording is compatible with Coptic Orthodox teaching.

You MUST NOT:
- Use Protestant, Evangelical, or Catholic terminology.
- Use modern Western theological expressions.
- Introduce doctrinal interpretation.

When uncertain, choose neutral Orthodox-safe wording
directly derived from the content.

────────────────────────────────────────
GOAL
────────────────────────────────────────
Generate stable, factual, SEO-friendly metadata
for a public Coptic Orthodox digital library.

The output must be:
- Deterministic and low-variation
- Descriptive, not interpretive
- Faithful to the uploaded content

────────────────────────────────────────
CONTENT TYPE
────────────────────────────────────────
{content_desc}

────────────────────────────────────────
FIELD REQUIREMENTS
────────────────────────────────────────

1. title_ar
- Arabic only
- 3–6 words
- Constructed using key terms found in the content
- No metaphor or emotional language

2. title_en
- English
- Same meaning as Arabic title
- Based on the same extracted content terms

3. description_ar
- Arabic
- 140–160 words
- Describe:
  • subject matter
  • scope
  • intended audience
- Use vocabulary found in the content where possible
- No inferred doctrine

4. description_en
- English
- Semantically aligned with Arabic description
- Same structure and factual meaning

5. tags
- Exactly 5–6 tags
- Arabic only
- Derived from:
  • repeated keywords
  • explicit themes
  • content type
- Avoid generic church tags unless they appear in the content

────────────────────────────────────────
EXTRACTION-FIRST RULE
────────────────────────────────────────
Before composing metadata:
- Identify the most important words and phrases in the content.
- Prefer frequency and prominence over assumed importance.

Do NOT invent themes.
Do NOT generalize.

────────────────────────────────────────
THEOLOGICAL SAFETY RULE
────────────────────────────────────────
If the content does not explicitly state a belief or doctrine:
- Do NOT infer it
- Do NOT explain it
- Do NOT summarize it

Remain strictly descriptive.

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────
Return ONLY valid JSON.
No explanations.
No additional text.

The JSON MUST strictly match the required schema.
"""
        
        return prompt
    
    def _validate_metadata(self, metadata: Dict) -> Dict[str, str]:
        """Validate and clean generated metadata"""
        
        # Default values
        defaults = {
            'title_ar': 'عنوان الملف',
            'title_en': 'File Title',
            'description_ar': 'وصف الملف',
            'description_en': 'File Description',
            'tags': []
        }
        
        # Clean and validate each field
        cleaned = {}
        
        # Titles
        cleaned['title_ar'] = str(metadata.get('title_ar', defaults['title_ar'])).strip()[:200]
        cleaned['title_en'] = str(metadata.get('title_en', defaults['title_en'])).strip()[:200]
        
        # Descriptions  
        cleaned['description_ar'] = str(metadata.get('description_ar', defaults['description_ar'])).strip()[:1000]
        cleaned['description_en'] = str(metadata.get('description_en', defaults['description_en'])).strip()[:1000]
        
        # Tags - ensure they're Arabic and clean
        tags = metadata.get('tags', [])
        if isinstance(tags, list):
            cleaned_tags = []
            for tag in tags[:6]:  # Max 6 tags to match prompt requirement
                tag_str = str(tag).strip()
                if tag_str and len(tag_str) <= 50:  # Max 50 chars per tag
                    cleaned_tags.append(tag_str)
            cleaned['tags'] = cleaned_tags
        else:
            cleaned['tags'] = []
            
        return cleaned


# Singleton instance
_gemini_service = None

def get_gemini_service() -> GeminiContentGenerator:
    """Get singleton instance of Gemini service"""
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiContentGenerator()
    return _gemini_service