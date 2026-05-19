"""
Base Gemini AI Service
Provides common functionality for all Gemini-based services to reduce code duplication.
"""
import json
import logging
import os
import time
from typing import Dict, Tuple, Optional
from django.conf import settings
from google import genai
from .gemini_rate_limit_service import get_gemini_rate_limit_service

logger = logging.getLogger(__name__)


class BaseGeminiService:
    """Base service class for Gemini AI operations"""
    
    # Model constants
    MODEL_3_FLASH = "gemini-3-flash-preview"
    MODEL_2_5_FLASH = "gemini-2.5-flash"
    MODEL_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    LARGE_FILE_UPLOAD_THRESHOLD_MB = 20
    CACHE_TTL_SECONDS = 86400
    FILE_READY_TIMEOUT_SECONDS = 90
    FILE_READY_POLL_INTERVAL_SECONDS = 2
    
    def __init__(self, default_model: str = None):
        """
        Initialize Gemini client with common configuration
        
        Args:
            default_model: Default model to use for this service
        """
        try:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")
                
            self.default_model = default_model or getattr(settings, 'GEMINI_MODEL', self.MODEL_2_5_FLASH)
            self.client = genai.Client(api_key=api_key)
            self.rate_limit_service = get_gemini_rate_limit_service()
            self._cached_content_names: dict[str, str] = {}
            
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
            self.rate_limit_service = None
    
    def is_available(self) -> bool:
        """Check if Gemini service is available"""
        return self.client is not None and self.rate_limit_service is not None
    
    def check_model_availability(self, model: str = None, operation_type: str = 'metadata') -> Tuple[bool, str, Optional[str]]:
        """
        Check if a specific model is available for use.
        
        Args:
            model: Model to check (uses default if None)
            operation_type: Type of operation ('metadata' or 'seo')
            
        Returns:
            Tuple of (is_available, message, fallback_model)
        """
        if not self.is_available():
            return False, "Gemini service not available", None
        
        target_model = model or self.default_model
        return self.rate_limit_service.check_availability(target_model, operation_type)

    def _get_file_size_mb(self, file_path: str) -> float:
        try:
            return os.path.getsize(file_path) / (1024 * 1024)
        except OSError:
            return 0.0
    
    def _upload_file(self, file_path: str):
        """Upload file to Gemini and return uploaded file object"""
        if not self.is_available():
            raise Exception("Gemini service not available")
        file_size_mb = self._get_file_size_mb(file_path)
        if file_size_mb >= self.LARGE_FILE_UPLOAD_THRESHOLD_MB:
            logger.info(
                "Uploading %s to Gemini Files API as a large file (%.2f MB)",
                file_path,
                file_size_mb,
            )
        else:
            logger.info(
                "Uploading %s to Gemini Files API (%.2f MB)",
                file_path,
                file_size_mb,
            )
        uploaded_file = self.client.files.upload(file=file_path)
        return self._wait_for_file_active(uploaded_file)
       

    def _wait_for_file_active(
        self,
        uploaded_file,
        timeout_seconds: int = None,
        poll_interval_seconds: int = None,
    ):
        """Poll Gemini until an uploaded file becomes ACTIVE."""
        file_name = getattr(uploaded_file, "name", None)
        if not file_name:
            return uploaded_file

        timeout_seconds = timeout_seconds or self.FILE_READY_TIMEOUT_SECONDS
        poll_interval_seconds = (
            poll_interval_seconds or self.FILE_READY_POLL_INTERVAL_SECONDS
        )
        deadline = time.monotonic() + timeout_seconds
        current_file = uploaded_file

        while True:
            state = getattr(current_file, "state", None)
            state_value = getattr(state, "value", state)

            if state_value == "ACTIVE":
                return current_file

            if state_value == "FAILED":
                raise Exception(f"Gemini file {file_name} failed processing before use")

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Gemini file {file_name} did not become ACTIVE within "
                    f"{timeout_seconds} seconds (last state: {state_value or 'unknown'})"
                )

            try:
                current_file = self.client.files.get(name=file_name)
            except Exception as exc:
                logger.debug(
                    "Waiting for Gemini file %s to become ACTIVE: %s",
                    file_name,
                    exc,
                )

            time.sleep(poll_interval_seconds)
    
    def _cleanup_file(self, uploaded_file):
        """Clean up uploaded file from Gemini"""
        try:
            self.client.files.delete(name=uploaded_file.name)
        except Exception as e:
            logger.warning(f"Failed to cleanup Gemini file: {e}")
    
    def _generate_content(
        self,
        prompt: str,
        uploaded_file,
        response_schema: dict,
        model: str = None,
        use_fallback: bool = True,
        system_instruction: Optional[str] = None,
        cache_key: Optional[str] = None,
        text_content: Optional[str] = None,
    ):
        """
        Generate content with Gemini using standard configuration
        
        Args:
            prompt: The prompt text
            uploaded_file: Uploaded file object from Gemini
            response_schema: JSON schema for response validation
            model: Specific model to use (uses default if None)
            use_fallback: Whether to use fallback model if primary fails
            
        Returns:
            Parsed JSON response
            
        Raises:
            Exception: If generation fails and no fallback is available
        """
        target_model = model or self.default_model
        
        # Check availability
        is_available, message, fallback_model = self.check_model_availability(target_model)
        
        if not is_available and use_fallback and fallback_model:
            logger.warning(f"{message}. Switching to fallback model: {fallback_model}")
            target_model = fallback_model
        elif not is_available:
            raise Exception(f"Model not available: {message}")
        
        try:
            contents = []
            if text_content:
                contents.append(text_content)
            if uploaded_file is not None:
                contents.append(uploaded_file)
            if not contents:
                contents.append(prompt)

            config = {
                "temperature": 0.1,  # Low temperature for deterministic outputs
                "top_p": 0.9,       # Nucleus sampling for consistency
                "top_k": 20,        # Limit token choices for predictability
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            }

            # Generate content
            response = self.client.models.generate_content(
                model=target_model,
                contents=contents,
                config=config,
            )
            
            # Record usage
            if self.rate_limit_service:
                self.rate_limit_service.record_usage(target_model)
            
            logger.info(f"Successfully generated content using model: {target_model}")
            return json.loads(response.text)
            
        except Exception as e:
            logger.error(f"Error generating content with {target_model}: {e}")
            
            # Try fallback if enabled and not already using it
            if use_fallback and fallback_model and target_model != fallback_model:
                logger.warning(f"Retrying with fallback model: {fallback_model}")
                return self._generate_content(prompt, uploaded_file, response_schema, fallback_model, use_fallback=False)
            
            raise
