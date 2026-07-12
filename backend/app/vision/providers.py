import base64
import json
import os
from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.constants import DEFAULT_GEMINI_MODEL, DEFAULT_TIMEOUT_SECONDS, VISION_PROMPT
from app.vision.errors import VisionAPIError, VisionConfigurationError, VisionParseError
from app.vision.parsing import extract_gemini_label
from app.vision.preprocessing import ImagePreprocessor, ProcessedImage
from app.vision.protocols import GeminiClientProtocol


class GeminiVisionService:
    """Extract label fields through the Gemini API."""

    def __init__(
        self,
        client: GeminiClientProtocol | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        """Configure the Gemini client, model, timeout, and image preprocessor."""
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key, timeout_seconds)

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Extract structured label fields from an image with Gemini."""
        # Normalize the image before building Gemini request parts.
        processed = self.preprocessor.process(image_bytes, content_type)

        # Request JSON output constrained by the ExtractedLabel schema.
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    self._image_part(processed),
                    VISION_PROMPT,
                ],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ExtractedLabel,
                    "temperature": 0,
                },
            )
        except ValidationError as exc:
            raise VisionParseError("Structured output failed validation") from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VisionParseError("Structured output could not be parsed") from exc
        except TimeoutError as exc:
            raise VisionAPIError("Gemini model request timed out") from exc
        except Exception as exc:
            raise VisionAPIError("Gemini model request failed") from exc

        # Validate the provider response against the backend schema.
        return extract_gemini_label(response)

    @staticmethod
    def _build_client(
        api_key: str | None, timeout_seconds: float
    ) -> GeminiClientProtocol:
        """Build a Gemini client from environment-backed credentials."""
        resolved_api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        if not resolved_api_key:
            raise VisionConfigurationError(
                "Set GEMINI_API_KEY to use GeminiVisionService"
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError(
                "google-genai is required for GeminiVisionService"
            ) from exc

        return genai.Client(
            api_key=resolved_api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    @staticmethod
    def _image_part(processed: ProcessedImage) -> Any:
        """Build the Gemini image part from processed image bytes."""
        try:
            from google.genai import types
        except ImportError:
            return {
                "inline_data": {
                    "mime_type": processed.content_type,
                    "data": base64.b64encode(processed.data).decode("ascii"),
                }
            }

        return types.Part.from_bytes(
            data=processed.data,
            mime_type=processed.content_type,
        )
