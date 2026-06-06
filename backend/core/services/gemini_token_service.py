import logging
from typing import List
from google import genai
from google.genai import types
from django.conf import settings

from .gemini_audit_helper import log_gemini_error

logger = logging.getLogger(__name__)


class GeminiTokenCountError(Exception):
    """Raised when token counting fails."""


class GeminiTokenService:
    """
    Counts tokens using the official Gemini SDK count_tokens() API.
    NEVER falls back to estimation — exact counts only.
    All failures are logged to Lifecycle Audit Logs.
    """

    def __init__(self):
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        self.client = genai.Client(api_key=api_key)

    def count_text_tokens(self, text: str, model: str, content_item=None) -> int:
        if not text:
            return 0
        try:
            response = self.client.models.count_tokens(
                model=model,
                contents=text,
            )
            return response.total_tokens
        except Exception as e:
            log_gemini_error(
                'gemini_token_count_failed',
                model=model, error=e, content_item=content_item,
                payload={'text_length': len(text)},
                message=f"count_tokens failed for text on {model}",
            )
            raise GeminiTokenCountError(
                f"count_tokens failed for model={model}: {e}"
            ) from e

    def count_multimodal_tokens(
        self,
        model: str,
        text_parts: List[str],
        uploaded_uris: List[tuple[str, str]] = None,
        content_item=None,
    ) -> int:
        parts: list[types.Part] = []
        for t in text_parts:
            if t:
                parts.append(types.Part(text=t))
        if uploaded_uris:
            for uri, mime in uploaded_uris:
                parts.append(types.Part.from_uri(file_uri=uri, mime_type=mime))

        if not parts:
            return 0

        content = types.Content(parts=parts, role="user")

        try:
            response = self.client.models.count_tokens(
                model=model,
                contents=[content],
            )
            return response.total_tokens
        except Exception as e:
            log_gemini_error(
                'gemini_token_count_failed',
                model=model, error=e, content_item=content_item,
                payload={'text_parts_count': len(text_parts), 'file_uris': [u for u, _ in (uploaded_uris or [])]},
                message=f"count_tokens failed for multimodal on {model}",
            )
            raise GeminiTokenCountError(
                f"count_tokens failed for multimodal content on model={model}: {e}"
            ) from e

    def count_file_tokens(
        self, model: str, file_uri: str, mime_type: str, prompt_text: str = "",
        content_item=None,
    ) -> int:
        return self.count_multimodal_tokens(
            model=model,
            text_parts=[prompt_text] if prompt_text else [],
            uploaded_uris=[(file_uri, mime_type)],
            content_item=content_item,
        )

    def extract_actual_tokens(self, response) -> int:
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            return response.usage_metadata.prompt_token_count or 0
        return 0

    def get_model_context_window(self, model: str) -> int:
        try:
            model_info = self.client.models.get(model=model)
            return model_info.input_token_limit or 128000
        except Exception as e:
            logger.warning(f"Failed to get model info for {model}: {e}")
            return 128000


# Singleton
_token_service = None

def get_gemini_token_service() -> GeminiTokenService:
    global _token_service
    if _token_service is None:
        _token_service = GeminiTokenService()
    return _token_service
