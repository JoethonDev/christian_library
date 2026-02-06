"""
Base Gemini AI Service
Provides common functionality for all Gemini-based services to reduce code duplication.
"""
import json
import logging
from typing import Dict, Tuple
from django.conf import settings
from google import genai

logger = logging.getLogger(__name__)


class BaseGeminiService:
    """Base service class for Gemini AI operations"""
    
    def __init__(self):
        """Initialize Gemini client with common configuration"""
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
    
    def _upload_file(self, file_path: str):
        """Upload file to Gemini and return uploaded file object"""
        if not self.is_available():
            raise Exception("Gemini service not available")
        return self.client.files.upload(file=file_path)
    
    def _cleanup_file(self, uploaded_file):
        """Clean up uploaded file from Gemini"""
        try:
            self.client.files.delete(name=uploaded_file.name)
        except Exception as e:
            logger.warning(f"Failed to cleanup Gemini file: {e}")
    
    def _generate_content(self, prompt: str, uploaded_file, response_schema: dict):
        """
        Generate content with Gemini using standard configuration
        
        Args:
            prompt: The prompt text
            uploaded_file: Uploaded file object from Gemini
            response_schema: JSON schema for response validation
            
        Returns:
            Parsed JSON response
        """
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt, uploaded_file],
            config={
                "temperature": 0.1,  # Low temperature for deterministic outputs
                "top_p": 0.9,       # Nucleus sampling for consistency
                "top_k": 20,        # Limit token choices for predictability
                "response_mime_type": "application/json",
                "response_schema": response_schema
            }
        )
        
        return json.loads(response.text)
