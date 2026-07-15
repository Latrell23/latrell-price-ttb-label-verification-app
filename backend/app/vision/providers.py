import base64
import json
import logging
import os
import time

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.constants import DEFAULT_TIMEOUT_SECONDS, VISION_PROMPT
from app.vision.errors import VisionAPIError, VisionConfigurationError, VisionParseError
from app.vision.parsing import extract_openai_label
from app.vision.preprocessing import ImagePreprocessor
from app.vision.protocols import OpenAIClientProtocol

LOGGER = logging.getLogger("app.main")
RETRYABLE_API_ERROR_NAMES = {"APIConnectionError", "InternalServerError"}
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_OPENAI_ATTEMPTS = 2
MIN_RETRY_TIMEOUT_SECONDS = 2.25
PROVIDER_COMPLETION_RESERVE_SECONDS = 0.15


class OpenAIVisionService:
    """Extract label fields through the OpenAI Responses API."""

    def __init__(
        self,
        client: OpenAIClientProtocol | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        """Configure the OpenAI client, model, timeout, and image preprocessor."""
        self.model = model or os.getenv("OPENAI_MODEL")
        if not self.model:
            raise VisionConfigurationError(
                "Set OPENAI_MODEL to use OpenAIVisionService"
            )
        self.reasoning_effort = reasoning_effort or os.getenv("OPENAI_REASONING_EFFORT")
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key, timeout_seconds)

    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
        *,
        deadline: float | None = None,
    ) -> ExtractedLabel:
        """Extract structured label fields from an image with OpenAI."""
        deadline = (
            time.monotonic() + self.timeout_seconds if deadline is None else deadline
        )
        preprocessing_started = time.monotonic()
        processed = self.preprocessor.process(image_bytes, content_type)
        LOGGER.info(
            "vision_preprocessing_complete",
            extra={
                "preprocessing_latency_ms": (
                    time.monotonic() - preprocessing_started
                )
                * 1000,
                "remaining_budget_ms": max(0.0, deadline - time.monotonic())
                * 1000,
            },
        )
        encoded_image = base64.b64encode(processed.data).decode("ascii")

        try:
            request: dict[str, object] = {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": VISION_PROMPT},
                            {
                                "type": "input_image",
                                "image_url": (
                                    f"data:{processed.content_type};base64,{encoded_image}"
                                ),
                                "detail": "high",
                            },
                        ],
                    }
                ],
                "text_format": ExtractedLabel,
                "store": False,
            }
            if self.reasoning_effort:
                request["reasoning"] = {"effort": self.reasoning_effort}

            response = self._parse_with_retry(request, deadline)
        except ValidationError as exc:
            raise VisionParseError("Structured output failed validation") from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VisionParseError("Structured output could not be parsed") from exc
        except VisionAPIError:
            raise
        except TimeoutError as exc:
            raise VisionAPIError(
                "OpenAI model request timed out",
                reason="provider_timeout",
            ) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "APITimeoutError":
                raise VisionAPIError(
                    "OpenAI model request timed out",
                    reason="provider_timeout",
                ) from exc
            if exc.__class__.__name__ in {
                "ContentFilterFinishReasonError",
                "LengthFinishReasonError",
            }:
                raise VisionParseError("Structured output was not completed") from exc
            raise VisionAPIError(
                "OpenAI model request failed",
                reason="provider_error",
            ) from exc

        return extract_openai_label(response)

    def _parse_with_retry(
        self,
        request: dict[str, object],
        deadline: float,
    ) -> object:
        """Parse a response with one retry while staying inside the service budget."""
        last_error: Exception | None = None

        for attempt in range(MAX_OPENAI_ATTEMPTS):
            remaining_seconds = (
                deadline
                - time.monotonic()
                - PROVIDER_COMPLETION_RESERVE_SECONDS
            )
            if remaining_seconds <= 0:
                raise VisionAPIError(
                    "Vision endpoint deadline exhausted before model request",
                    reason="endpoint_deadline",
                )

            attempt_started = time.monotonic()
            try:
                response = self.client.responses.parse(
                    **request,
                    timeout=remaining_seconds,
                )
                LOGGER.info(
                    "vision_provider_attempt_complete",
                    extra={
                        "attempt": attempt + 1,
                        "attempt_latency_ms": (
                            time.monotonic() - attempt_started
                        )
                        * 1000,
                        "remaining_budget_ms": max(
                            0.0,
                            deadline - time.monotonic(),
                        )
                        * 1000,
                        "openai_request_id": getattr(
                            response,
                            "_request_id",
                            getattr(response, "request_id", None),
                        ),
                        "status": "success",
                    },
                )
                return response
            except Exception as exc:
                attempt_latency_ms = (time.monotonic() - attempt_started) * 1000
                remaining_after_failure = (
                    deadline
                    - time.monotonic()
                    - PROVIDER_COMPLETION_RESERVE_SECONDS
                )
                LOGGER.warning(
                    "vision_provider_attempt_failed",
                    extra={
                        "attempt": attempt + 1,
                        "attempt_latency_ms": attempt_latency_ms,
                        "remaining_budget_ms": max(0.0, remaining_after_failure)
                        * 1000,
                        "exception_type": exc.__class__.__name__,
                        "upstream_status": getattr(exc, "status_code", None),
                        "openai_request_id": getattr(exc, "request_id", None),
                    },
                )
                if not _is_retryable_api_error(exc):
                    raise
                last_error = exc
                if attempt == MAX_OPENAI_ATTEMPTS - 1:
                    break
                if remaining_after_failure < MIN_RETRY_TIMEOUT_SECONDS:
                    break

        if last_error is not None:
            raise last_error
        raise TimeoutError("OpenAI model request timed out")

    @staticmethod
    def _build_client(
        api_key: str | None, timeout_seconds: float
    ) -> OpenAIClientProtocol:
        """Build an OpenAI client from environment-backed credentials."""
        resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_api_key:
            raise VisionConfigurationError(
                "Set OPENAI_API_KEY to use OpenAIVisionService"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError(
                "openai is required for OpenAIVisionService"
            ) from exc

        return OpenAI(
            api_key=resolved_api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def close(self) -> None:
        """Close the shared OpenAI HTTP client."""
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


def _is_retryable_api_error(exc: Exception) -> bool:
    if exc.__class__.__name__ in RETRYABLE_API_ERROR_NAMES:
        return True

    status_code = getattr(exc, "status_code", None)
    return status_code in RETRYABLE_STATUS_CODES
