"""
Gemini AI Service for Metadata Generation
Handles content metadata generation using Google Gemini API with standardized JSON response format.
"""
import json
import logging
from typing import Dict, Tuple
from django.conf import settings
from google import genai

logger = logging.getLogger(__name__)


class GeminiMetadataService:
    """Service for generating content metadata using Gemini AI"""
    
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
                "en": {"title": "...", "description": "..."},
                "ar": {"title": "...", "description": "..."}
            }
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create metadata prompt
            prompt = self._create_metadata_prompt(content_type)
            
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
                                    "title": {"type": "string"},
                                    "description": {"type": "string"}
                                },
                                "required": ["title", "description"]
                            },
                            "ar": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "description": {"type": "string"}
                                },
                                "required": ["title", "description"]
                            }
                        },
                        "required": ["en", "ar"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse and validate response
            metadata = json.loads(response.text)
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
4. Ensure all content reflects Coptic Orthodox context
5. Use natural, clear language appropriate for church members

THEOLOGICAL ACCURACY:
- Reference specific Coptic Orthodox saints, liturgies, or teachings when applicable
- Use proper terminology from Coptic tradition
- Ensure theological soundness aligned with Coptic Orthodox doctrine

Return metadata in the following JSON format:
{{
  "en": {{
    "title": "English title",
    "description": "English description"
  }},
  "ar": {{
    "title": "Arabic title",
    "description": "Arabic description"
  }}
}}"""
    
    def _validate_metadata(self, metadata: Dict) -> Dict:
        """Validate and clean metadata"""
        cleaned = {}
        
        for lang in ['en', 'ar']:
            if lang in metadata:
                lang_data = metadata[lang]
                cleaned[lang] = {
                    'title': str(lang_data.get('title', ''))[:100].strip(),
                    'description': str(lang_data.get('description', ''))[:200].strip()
                }
            else:
                cleaned[lang] = {'title': '', 'description': ''}
        
        return cleaned


def get_gemini_metadata_service() -> GeminiMetadataService:
    """Get or create Gemini metadata service singleton"""
    if not hasattr(get_gemini_metadata_service, '_instance'):
        get_gemini_metadata_service._instance = GeminiMetadataService()
    return get_gemini_metadata_service._instance
