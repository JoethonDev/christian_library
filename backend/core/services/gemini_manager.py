"""
Gemini Manager Service
Central manager for all Gemini operations with intelligent fallback logic and rate limiting.
"""
import logging
from typing import Dict, Tuple
from .gemini_metadata_service import get_gemini_metadata_service
from .gemini_seo_service import get_gemini_seo_service
from .gemini_rate_limit_service import get_gemini_rate_limit_service

logger = logging.getLogger(__name__)


class GeminiManager:
    """
    Central manager for Gemini AI operations.
    Handles rate limiting, fallback logic, and service coordination.
    """
    
    def __init__(self):
        """Initialize Gemini manager with all services"""
        self.metadata_service = get_gemini_metadata_service()
        self.seo_service = get_gemini_seo_service()
        self.rate_limit_service = get_gemini_rate_limit_service()
    
    def generate_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate metadata using Gemini 2.5 Flash with automatic fallback.
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
        """
        # Check rate limit before attempting
        is_available, message, fallback_model = self.rate_limit_service.check_availability(
            self.metadata_service.default_model, 
            operation_type='metadata'
        )
        
        if not is_available:
            logger.warning(f"Metadata generation rate limit check: {message}")
            if fallback_model:
                logger.info(f"Will use fallback model: {fallback_model}")
        
        try:
            return self.metadata_service.generate_metadata(file_path, content_type)
        except Exception as e:
            logger.error(f"Metadata generation failed: {e}")
            return False, {"error": str(e)}
    
    def generate_seo(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate SEO metadata using Gemini 3 Flash with automatic fallback.
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, seo_data: dict)
        """
        # Check rate limit before attempting
        is_available, message, fallback_model = self.rate_limit_service.check_availability(
            self.seo_service.default_model,
            operation_type='seo'
        )
        
        if not is_available:
            logger.warning(f"SEO generation rate limit check: {message}")
            if fallback_model:
                logger.info(f"Will use fallback model: {fallback_model}")
        
        try:
            return self.seo_service.generate_seo(file_path, content_type)
        except Exception as e:
            logger.error(f"SEO generation failed: {e}")
            return False, {"error": str(e)}
    
    def get_rate_limit_status(self) -> Dict:
        """
        Get current rate limit status for all models.
        
        Returns:
            Dict with rate limit info for all models
        """
        return self.rate_limit_service.get_all_models_info()
    
    def check_metadata_availability(self) -> Tuple[bool, str]:
        """
        Check if metadata generation is currently available.
        
        Returns:
            Tuple of (is_available: bool, message: str)
        """
        is_available, message, _ = self.rate_limit_service.check_availability(
            self.metadata_service.default_model,
            operation_type='metadata'
        )
        return is_available, message
    
    def check_seo_availability(self) -> Tuple[bool, str]:
        """
        Check if SEO generation is currently available.
        
        Returns:
            Tuple of (is_available: bool, message: str)
        """
        is_available, message, _ = self.rate_limit_service.check_availability(
            self.seo_service.default_model,
            operation_type='seo'
        )
        return is_available, message
    
    def refresh_rate_limits(self) -> Dict:
        """
        Force refresh rate limit data from Gemini API.
        
        Returns:
            Dict with updated rate limit info for all models
        """
        return self.rate_limit_service.get_all_models_info(force_refresh=True)


# Singleton instance
_gemini_manager = None

def get_gemini_manager() -> GeminiManager:
    """Get or create Gemini manager singleton"""
    global _gemini_manager
    if _gemini_manager is None:
        _gemini_manager = GeminiManager()
    return _gemini_manager
