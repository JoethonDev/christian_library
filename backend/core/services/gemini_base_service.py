"""
Base Gemini AI Service
Provides common functionality for all Gemini-based services to reduce code duplication.
"""
import json
import logging
import os
import time
from typing import Tuple, Optional
from django.conf import settings
from google import genai
from apps.media_manager.models import GeminiModelSetting, GeminiGenerationAttempt
from .gemini_rate_limit_service import get_gemini_rate_limit_service, get_model_selection_strategy
from .gemini_token_service import get_gemini_token_service, GeminiTokenCountError
from .gemini_audit_helper import log_gemini_error
from .gemini_lease_service import get_gemini_lease_service
from google.genai.types import FinishReason

logger = logging.getLogger(__name__)


class BaseGeminiService:
    """Base service class for Gemini AI operations"""

    LARGE_FILE_UPLOAD_THRESHOLD_MB = 20
    CACHE_TTL_SECONDS = 86400
    FILE_READY_TIMEOUT_SECONDS = 90
    FILE_READY_POLL_INTERVAL_SECONDS = 2

    def __init__(self, default_model: str = None):
        """
        Initialize Gemini client with common configuration

        Args:
            default_model: Specific model to use. If None, reads from GeminiModelSetting where is_default=True.
        """
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")

        if default_model is None:
            try:
                default_setting = GeminiModelSetting.objects.get(is_enabled=True, is_default=True)
                default_model = default_setting.model_key
            except GeminiModelSetting.DoesNotExist:
                first_enabled = GeminiModelSetting.objects.filter(
                    is_enabled=True, archived_at__isnull=True
                ).order_by('fallback_priority').first()
                if first_enabled is not None:
                    default_model = first_enabled.model_key
                else:
                    default_model = None

        if default_model is None:
            raise RuntimeError(
                "No default Gemini model configured. "
                "Ensure a GeminiModelSetting with is_default=True and is_enabled=True exists."
            )

        self.default_model = default_model
        self.client = genai.Client(api_key=api_key)
        self.rate_limit_service = get_gemini_rate_limit_service()

    def is_available(self) -> bool:
        """Check if Gemini service is available"""
        return self.client is not None and self.rate_limit_service is not None

    def check_model_availability(self, model: str = None, operation_type: str = 'metadata', estimated_tokens: int = 0, content_item=None) -> Tuple[bool, str, Optional[str]]:
        """
        Check if a specific model is available for use.

        Args:
            model: Model to check (uses default if None)
            operation_type: Type of operation ('metadata' or 'seo')
            estimated_tokens: Estimated token count for the request
            content_item: ContentItem for audit trail

        Returns:
            Tuple of (is_available, message, fallback_model)
        """
        if not self.is_available():
            return False, "Gemini service not available", None

        target_model = model or self.default_model
        return self.rate_limit_service.check_availability(target_model, operation_type, estimated_tokens, content_item)

    def _check_context_window(self, model, total_tokens, content_item=None):
        """Check if total_tokens exceeds model context window. Logs audit on violation."""
        token_service = get_gemini_token_service()
        max_window = token_service.get_model_context_window(model)
        if total_tokens > max_window:
            log_gemini_error(
                'gemini_context_window_exceeded',
                model=model, content_item=content_item,
                payload={'total_tokens': total_tokens, 'max_window': max_window},
                message=f"Input ({total_tokens} tokens) exceeds {model} context window ({max_window})",
            )
            raise Exception(
                f"Input ({total_tokens} tokens) exceeds {model} context window ({max_window})"
            )

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

    def _create_attempt(self, content_item, requested_model_key, resolved_model_key, operation_type):
        """Create a GeminiGenerationAttempt row before starting generation."""
        try:
            return GeminiGenerationAttempt.objects.create(
                content_item=content_item,
                requested_model_key=requested_model_key,
                resolved_model_key=resolved_model_key,
                operation_type=operation_type,
                status=GeminiGenerationAttempt.Status.STARTED,
                success=None,
            )
        except Exception as e:
            logger.error(f"Failed to create Gemini attempt record: {e}")
            return None

    def _finalize_attempt(self, attempt, resolved_model, status, success, error_message=None, response_time_ms=None):
        """Update the attempt row after generation completes."""
        if attempt is None:
            return
        try:
            attempt.resolved_model_key = resolved_model
            attempt.status = status
            attempt.success = success
            attempt.error_message = error_message
            attempt.response_time_ms = response_time_ms
            attempt.save(update_fields=[
                'resolved_model_key', 'status', 'success',
                'error_message', 'response_time_ms'
            ])
        except Exception as e:
            logger.error(f"Failed to finalize Gemini attempt record: {e}")

    def _cleanup_file(self, uploaded_file):
        """Clean up uploaded file from Gemini"""
        try:
            self.client.files.delete(name=uploaded_file.name)
        except Exception as e:
            logger.warning(f"Failed to cleanup Gemini file: {e}")

    def _parse_json_response(self, response, model, content_item=None):
        """Parse JSON from Gemini response with recovery for malformed output."""
        raw = response.text
        if not raw:
            raise ValueError("Empty response from Gemini")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(
                "Malformed JSON from %s (pos %d): %.500s",
                model, e.pos, raw,
            )
            log_gemini_error(
                'gemini_malformed_json',
                model=model, content_item=content_item,
                payload={'error_position': e.pos, 'response_length': len(raw)},
                message=f"Malformed JSON response from {model}: {e}",
            )
            cleaned = raw.strip()
            if cleaned.endswith(',]'):
                cleaned = cleaned[:-2] + ']'
            if cleaned.endswith(',}'):
                cleaned = cleaned[:-2] + '}'
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
            error_msg = f"Malformed JSON response from Gemini: {e}"
            raise ValueError(error_msg) from e

    def _generate_content(
        self,
        prompt: str,
        uploaded_file,
        response_schema: dict,
        model: str = None,
        use_fallback: bool = True,
        use_scheduling: bool = False,
        text_content: Optional[str] = None,
        content_item=None,
        operation_type: str = GeminiGenerationAttempt.OperationType.COMBINED,
    ):
        """
        Generate content with Gemini using standard configuration.
        Uses exact token counting via Gemini SDK, ModelSelectionStrategy for model selection,
        and logs all failures to Lifecycle Audit Logs.

        Args:
            prompt: The prompt text
            uploaded_file: Uploaded file object from Gemini
            response_schema: JSON schema for response validation
            model: Specific model to use (uses default if None)
            use_fallback: Whether to use fallback model if primary fails
            use_scheduling: If True, defer to Redis ZSET queue when lease unavailable
            content_item: ContentItem instance to track this attempt (optional)
            operation_type: Type of generation ('combined', 'metadata', 'seo')

        Returns:
            Parsed JSON response

        Raises:
            Exception: If generation fails and no fallback is available
        """
        target_model = model or self.default_model
        requested_model_key = model or self.default_model
        token_service = get_gemini_token_service()
        strategy = get_model_selection_strategy()

        # ---- STEP 1: Count tokens exactly (Gemini SDK) ----
        text_parts = []
        if text_content:
            text_parts.append(text_content)
        text_parts.append(prompt)

        estimated_tokens = 0
        try:
            if uploaded_file is not None:
                file_uri = getattr(uploaded_file, 'uri', None)
                mime = getattr(uploaded_file, 'mime_type', 'application/octet-stream')
                if file_uri:
                    estimated_tokens = token_service.count_multimodal_tokens(
                        model=target_model,
                        text_parts=text_parts,
                        uploaded_uris=[(file_uri, mime)],
                        content_item=content_item,
                    )
                else:
                    estimated_tokens = token_service.count_text_tokens(
                        " ".join(text_parts), target_model, content_item=content_item
                    )
            else:
                estimated_tokens = token_service.count_text_tokens(
                    " ".join(text_parts), target_model, content_item=content_item
                )
        except GeminiTokenCountError:
            logger.warning(f"Token counting failed for {target_model}, proceeding without pre-flight count")
            estimated_tokens = 0

        # ---- STEP 2: Check context window ----
        if estimated_tokens > 0:
            self._check_context_window(target_model, estimated_tokens, content_item)

        # ---- STEP 3: Scored model selection + availability check ----
        selected_model = strategy.select_model(target_model, estimated_tokens)

        is_available, message, fallback_model = self.check_model_availability(
            selected_model, operation_type, estimated_tokens, content_item
        )

        if not is_available and use_fallback:
            fallback = strategy.get_fallback(selected_model, estimated_tokens) or fallback_model
            if fallback:
                logger.warning(f"{message}. Switching to fallback: {fallback}")
                selected_model = fallback
                is_available, message, _ = self.check_model_availability(
                    selected_model, operation_type, estimated_tokens, content_item
                )
            else:
                log_gemini_error(
                    'gemini_fallback_exhausted',
                    model=target_model, content_item=content_item,
                    payload={'estimated_tokens': estimated_tokens, 'tried_models': [target_model, fallback_model]},
                    message="All models exhausted, no fallback available",
                )

        if not is_available:
            raise Exception(f"Model not available: {message}")

        # ---- STEP 4: Acquire lease (concurrency control) ----
        lease_service = get_gemini_lease_service()
        max_concurrency = 3
        max_output_tokens = 65536
        try:
            setting = GeminiModelSetting.objects.get(model_key=selected_model)
            max_concurrency = setting.max_concurrency
            max_output_tokens = setting.max_input_tokens or 65536
        except GeminiModelSetting.DoesNotExist:
            pass

        lease_acquired = lease_service.acquire(selected_model, max_concurrency)
        if not lease_acquired:
            if use_scheduling:
                from .gemini_scheduler_service import get_gemini_scheduler_service
                scheduler = get_gemini_scheduler_service()
                request_id = scheduler.schedule_request(
                    model_key=selected_model,
                    prompt=prompt,
                    response_schema=response_schema,
                    delay_seconds=60,
                    text_content=text_content,
                    content_item_id=str(content_item.id) if content_item else None,
                    operation_type=operation_type,
                )
                logger.info("Lease unavailable for %s, deferred as %s", selected_model, request_id)
                return {"status": "deferred", "request_id": request_id, "model": selected_model}
            raise Exception(f"No lease available for {selected_model} (max concurrency: {max_concurrency})")

        # ---- STEP 5: Create attempt + make API call ----
        attempt = None
        if content_item is not None:
            attempt = self._create_attempt(content_item, requested_model_key, selected_model, operation_type)

        start_time = time.monotonic()

        try:
            contents = []
            if text_content:
                contents.append(text_content)
            if uploaded_file is not None:
                contents.append(uploaded_file)
            if not contents:
                contents.append(prompt)

            config = {
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 20,
                "max_output_tokens": max_output_tokens,
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            }

            response = self.client.models.generate_content(
                model=selected_model,
                contents=contents,
                config=config,
            )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # ---- STEP 6: Record actual tokens (authoritative post-hoc) ----
            # Must happen before any truncation/error check — the API call was
            # already made and consumed quota even if the response is truncated.
            actual_tokens = token_service.extract_actual_tokens(response)
            if self.rate_limit_service:
                self.rate_limit_service.record_usage(
                    selected_model,
                    actual_tokens=actual_tokens or estimated_tokens or None,
                    content_item=content_item,
                )

            # Check for blocked or truncated content
            try:
                candidate = response.candidates[0]
                finish_reason = candidate.finish_reason
                if finish_reason is not None and finish_reason != FinishReason.STOP:
                    reason_name = getattr(finish_reason, 'name', str(finish_reason))
                    if finish_reason == FinishReason.MAX_TOKENS:
                        log_gemini_error(
                            'gemini_response_truncated',
                            model=selected_model, content_item=content_item,
                            payload={'finish_reason': reason_name, 'response_length': len(response.text) if response.text else 0},
                            message=f"Response from {selected_model} was truncated (MAX_TOKENS, {len(response.text or '')} chars)",
                        )
                        if attempt is not None:
                            self._finalize_attempt(
                                attempt, selected_model,
                                GeminiGenerationAttempt.Status.FAILURE, False,
                                error_message=f"Gemini response truncated at {len(response.text or '')} chars (max_output_tokens={max_output_tokens})",
                                response_time_ms=elapsed_ms,
                            )
                        raise Exception(
                            f"Gemini response was truncated (max_output_tokens={max_output_tokens}). "
                            f"Got {len(response.text or '')} chars, finish_reason={reason_name}"
                        )
                    else:
                        log_gemini_error(
                            'gemini_content_blocked',
                            model=selected_model, content_item=content_item,
                            payload={'block_reason': reason_name, 'finish_reason': reason_name},
                        )
                        if attempt is not None:
                            self._finalize_attempt(
                                attempt, selected_model,
                                GeminiGenerationAttempt.Status.FAILURE, False,
                                error_message=f"Content blocked: finish_reason={reason_name}",
                                response_time_ms=elapsed_ms,
                            )
                        raise Exception(f"Content blocked by Gemini: finish_reason={reason_name}")
            except (AttributeError, IndexError):
                pass

            if attempt is not None:
                self._finalize_attempt(
                    attempt, selected_model,
                    GeminiGenerationAttempt.Status.SUCCESS, True,
                    response_time_ms=elapsed_ms,
                )

            logger.info(f"Successfully generated content using model: {selected_model}")
            return self._parse_json_response(response, selected_model, content_item)

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            log_gemini_error(
                'gemini_generation_failure',
                model=selected_model, error=e, content_item=content_item,
                payload={'operation_type': operation_type, 'response_time_ms': elapsed_ms},
                message=str(e)[:500],
            )

            if attempt is not None:
                self._finalize_attempt(
                    attempt, selected_model,
                    GeminiGenerationAttempt.Status.FAILURE, False,
                    error_message=str(e), response_time_ms=elapsed_ms,
                )

            if use_fallback and fallback_model and selected_model != fallback_model:
                logger.warning(f"Retrying with fallback model: {fallback_model}")
                return self._generate_content(
                    prompt, uploaded_file, response_schema, fallback_model,
                    use_fallback=False, text_content=text_content,
                    content_item=content_item, operation_type=operation_type,
                )

            raise

        finally:
            lease_service.release(selected_model)
