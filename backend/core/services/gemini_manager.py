"""
Gemini Manager Service
Central manager for all Gemini operations with intelligent fallback logic and rate limiting.
"""
import logging
from typing import Dict, Tuple
from django.apps import apps
from apps.media_manager.models import GeminiGenerationAttempt
from .gemini_metadata_service import get_gemini_metadata_service
from .gemini_seo_service import get_gemini_seo_service
from .gemini_rate_limit_service import get_gemini_rate_limit_service
from .gemini_reporting_service import get_gemini_reporting_service

logger = logging.getLogger(__name__)


def _get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')


def _create_blocked_attempt(content_item, requested_model_key, operation_type, error_message):
    """Create a blocked GeminiGenerationAttempt when rate limit prevents the call."""
    try:
        GeminiGenerationAttempt.objects.create(
            content_item=content_item,
            requested_model_key=requested_model_key,
            resolved_model_key=None,
            operation_type=operation_type,
            status=GeminiGenerationAttempt.Status.BLOCKED,
            success=False,
            error_message=error_message,
        )
    except Exception as e:
        logger.error(f"Failed to create blocked Gemini attempt record: {e}")


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
        self.reporting_service = get_gemini_reporting_service()
    
    def generate_metadata(self, file_path: str, content_type: str, content_item=None) -> Tuple[bool, Dict]:
        """
        Generate metadata using Gemini with automatic fallback.

        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            content_item: Optional ContentItem instance for attempt tracking

        Returns:
            Tuple of (success: bool, metadata: dict)
        """
        target_model = self.metadata_service.default_model

        is_available, message, fallback_model = self.rate_limit_service.check_availability(
            target_model, operation_type='metadata'
        )

        if not is_available:
            logger.warning(f"Metadata generation rate limit check: {message}")
            if content_item is not None:
                _create_blocked_attempt(content_item, target_model, 'metadata', message)
            return False, {"error": message}

        try:
            return self.metadata_service.generate_metadata(file_path, content_type, content_item=content_item)
        except Exception as e:
            logger.error(f"Metadata generation failed: {e}")
            return False, {"error": str(e)}
    
    def generate_seo(self, file_path: str, content_type: str, context_text: str = None, content_item=None) -> Tuple[bool, Dict]:
        """
        Generate SEO metadata using Gemini with automatic fallback.

        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            context_text: Optional extracted text
            content_item: Optional ContentItem instance for attempt tracking

        Returns:
            Tuple of (success: bool, seo_data: dict)
        """
        target_model = self.seo_service.default_model

        is_available, message, fallback_model = self.rate_limit_service.check_availability(
            target_model, operation_type='seo'
        )

        if not is_available:
            logger.warning(f"SEO generation rate limit check: {message}")
            if content_item is not None:
                _create_blocked_attempt(content_item, target_model, 'seo', message)
            return False, {"error": message}

        try:
            return self.seo_service.generate_seo(file_path, content_type, context_text=context_text, content_item=content_item)
        except Exception as e:
            logger.error(f"SEO generation failed: {e}")
            return False, {"error": str(e)}

    def generate_combined_ai_data(self, contentitem_id: str, file_path: str, content_type: str, context_text: str = None) -> Tuple[bool, Dict]:
        """
        Generate combined metadata + SEO output with one Gemini call.

        Args:
            contentitem_id: UUID of the ContentItem (required for attempt tracking)
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            context_text: Optional extracted text

        Returns:
            Tuple of (success: bool, combined_data: dict)
        """
        ContentItem = _get_contentitem_model()
        try:
            content_item = ContentItem.objects.get(id=contentitem_id)
        except ContentItem.DoesNotExist:
            logger.error(f"ContentItem {contentitem_id} not found for combined generation")
            return False, {"error": "ContentItem not found"}

        target_model = self.seo_service.default_model

        is_available, message, _ = self.rate_limit_service.check_availability(
            target_model, operation_type='combined'
        )

        if not is_available:
            logger.warning(f"Combined Gemini generation rate limit check: {message}")
            _create_blocked_attempt(content_item, target_model, 'combined', message)
            return False, {"error": message}

        try:
            return self.seo_service.generate_combined(file_path, content_type, context_text=context_text, content_item=content_item)
        except Exception as e:
            logger.error(f"Combined Gemini generation failed: {e}")
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
