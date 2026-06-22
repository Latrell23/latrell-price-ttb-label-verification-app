import base64
import json
import os
from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.constants import DEFAULT_TIMEOUT_SECONDS, DEFAULT_VISION_MODEL, VISION_PROMPT
from app.vision.errors import VisionAPIError, VisionConfigurationError, VisionParseError
from app.vision.parsing import extract_gemini_label, extract_openai_label
from app.vision.preprocessing import ImagePreprocessor, ProcessedImage
from app.vision.protocols import GeminiClientProtocol, OpenAIClientProtocol


class OpenAIVisionService:
    """Extract label fields through the OpenAI Responses API."""

    def __init__(
        self,
        client: OpenAIClientProtocol | None = None,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_VISION_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        """Configure the OpenAI client, model, timeout, and image preprocessor."""
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key, timeout_seconds)

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Extract structured label fields from an image with OpenAI."""
        # Normalize the image and encode it for the Responses API.
        processed = self.preprocessor.process(image_bytes, content_type)
        data_url = _to_data_url(processed.data, processed.content_type)

        # Request schema-constrained extraction from the model.
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": VISION_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Extract the visible TTB label fields from this image.",
                            },
                            {
                                "type": "input_image",
                                "image_url": data_url,
                                "detail": "high",
                            },
                        ],
                    },
                ],
                text_format=ExtractedLabel,
                reasoning={"effort": "low"},
                text={"verbosity": "low"},
                timeout=self.timeout_seconds,
            )
        except ValidationError as exc:
            raise VisionParseError("Structured output failed validation") from exc
        except (ValueError, TypeError) as exc:
            raise VisionParseError("Structured output could not be parsed") from exc
        except TimeoutError as exc:
            raise VisionAPIError("Vision model request timed out") from exc
        except Exception as exc:
            raise VisionAPIError("Vision model request failed") from exc

        # Validate the provider response against the backend schema.
        return extract_openai_label(response)

    @staticmethod
    def _build_client(
        api_key: str | None, timeout_seconds: float
    ) -> OpenAIClientProtocol:
        """Build an OpenAI client from environment-backed credentials."""
        resolved_api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("VISION_MODEL_API_KEY")
        )
        if not resolved_api_key:
            raise VisionConfigurationError(
                "Set OPENAI_API_KEY or VISION_MODEL_API_KEY to use OpenAIVisionService"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError(
                "openai is required for OpenAIVisionService"
            ) from exc

        return OpenAI(api_key=resolved_api_key, timeout=timeout_seconds)


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
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_VISION_MODEL
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key)

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
    def _build_client(api_key: str | None) -> GeminiClientProtocol:
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
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError(
                "google-genai is required for GeminiVisionService"
            ) from exc

        return genai.Client(api_key=resolved_api_key)

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


def _to_data_url(image_bytes: bytes, content_type: str) -> str:
    """Encode image bytes as a data URL for OpenAI image input."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
