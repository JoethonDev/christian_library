"""
Gemini AI Service for Metadata Generation
Handles content metadata generation using Google Gemini API with standardized JSON response format.
"""
import logging
from typing import Dict, Tuple
from .gemini_base_service import BaseGeminiService

logger = logging.getLogger(__name__)


class GeminiMetadataService(BaseGeminiService):
    """Service for generating content metadata using Gemini AI"""
    
    def generate_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate metadata for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
            Metadata follows standardized JSON format:
            {
                "en": {"title": "...", "description": "...", "tags": [...]},
                "ar": {"title": "...", "description": "...", "tags": [...]}
            }
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self._upload_file(file_path)
            
            # Create metadata prompt
            prompt = self._create_metadata_prompt(content_type)
            
            # Define response schema with tags
            response_schema = {
                "type": "object",
                "properties": {
                    "en": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6
                            }
                        },
                        "required": ["title", "description", "tags"]
                    },
                    "ar": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6
                            }
                        },
                        "required": ["title", "description", "tags"]
                    }
                },
                "required": ["en", "ar"]
            }
            
            # Generate content with Gemini
            metadata = self._generate_content(prompt, uploaded_file, response_schema)
            
            # Clean up uploaded file
            self._cleanup_file(uploaded_file)
            
            # Validate and clean response
            cleaned_metadata = self._validate_metadata(metadata)
            
            logger.info(f"Successfully generated metadata for {content_type} file")
            return True, cleaned_metadata
            
        except Exception as e:
            logger.error(f"Error generating metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
    
    def _create_metadata_prompt(self, content_type: str) -> str:
        """Create metadata generation prompt"""
        
        content_type_map = {
            'video': 'sermon, hymn, or teaching video',
            'audio': 'sermon, hymn, prayer, or teaching recording',
            'pdf': 'book, article, or teaching document'
        }
        
        content_description = content_type_map.get(content_type, 'content')
        
        return f"""You are analyzing a {content_description} for the Christian Coptic Orthodox Church of Egypt library.

CONTEXT AND NICHE CONSTRAINT:
This content library exclusively serves the Christian Coptic Orthodox Church of Egypt community. All metadata MUST be:
- Grounded in Coptic Orthodox theology, liturgy, and traditions
- Relevant to Egyptian Coptic Christian heritage and practices
- Appropriate for church education, worship, and spiritual formation

Generate descriptive metadata in both English and Arabic based on the actual content of this file.

REQUIREMENTS:
1. Analyze the actual content carefully
2. Create concise, accurate titles (max 100 characters)
3. Write descriptive summaries (2-3 sentences, max 200 characters)
4. Generate 3-6 relevant tags/keywords for categorization
5. Ensure all content reflects Coptic Orthodox context
6. Use natural, clear language appropriate for church members

TAGS GUIDANCE:
- Tags should be short phrases or single words (e.g., "liturgy", "hymns", "st. george", "baptism")
- Use both specific (saint names, feast names) and general (prayer, worship) tags
- Include liturgical seasons or occasions when applicable
- Keep tags in the respective language (English tags in English, Arabic tags in Arabic)

THEOLOGICAL ACCURACY:
- Reference specific Coptic Orthodox saints, liturgies, or teachings when applicable
- Use proper terminology from Coptic tradition
- Ensure theological soundness aligned with Coptic Orthodox doctrine

Return metadata in the following JSON format:
{{
  "en": {{
    "title": "English title",
    "description": "English description",
    "tags": ["tag1", "tag2", "tag3"]
  }},
  "ar": {{
    "title": "Arabic title",
    "description": "Arabic description",
    "tags": ["علامة1", "علامة2", "علامة3"]
  }}
}}"""
    
    def _validate_metadata(self, metadata: Dict) -> Dict:
        """Validate and clean metadata"""
        cleaned = {}
        
        for lang in ['en', 'ar']:
            if lang in metadata:
                lang_data = metadata[lang]
                # Get tags and validate
                tags = lang_data.get('tags', [])
                if isinstance(tags, list):
                    # Clean and limit tags
                    tags = [str(tag)[:50].strip() for tag in tags[:6] if tag]
                else:
                    tags = []
                
                cleaned[lang] = {
                    'title': str(lang_data.get('title', ''))[:100].strip(),
                    'description': str(lang_data.get('description', ''))[:200].strip(),
                    'tags': tags
                }
            else:
                cleaned[lang] = {'title': '', 'description': '', 'tags': []}
        
        return cleaned


def get_gemini_metadata_service() -> GeminiMetadataService:
    """Get or create Gemini metadata service singleton"""
    if not hasattr(get_gemini_metadata_service, '_instance'):
        get_gemini_metadata_service._instance = GeminiMetadataService()
    return get_gemini_metadata_service._instance
