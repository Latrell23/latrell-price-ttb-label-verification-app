import base64
import json
import os

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.constants import DEFAULT_TIMEOUT_SECONDS, VISION_PROMPT
from app.vision.errors import VisionAPIError, VisionConfigurationError, VisionParseError
from app.vision.parsing import extract_openai_label
from app.vision.preprocessing import ImagePreprocessor
from app.vision.protocols import OpenAIClientProtocol


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
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Extract structured label fields from an image with OpenAI."""
        processed = self.preprocessor.process(image_bytes, content_type)
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

            response = self.client.responses.parse(**request)
        except ValidationError as exc:
            raise VisionParseError("Structured output failed validation") from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VisionParseError("Structured output could not be parsed") from exc
        except TimeoutError as exc:
            raise VisionAPIError("OpenAI model request timed out") from exc
        except Exception as exc:
            if exc.__class__.__name__ == "APITimeoutError":
                raise VisionAPIError("OpenAI model request timed out") from exc
            if exc.__class__.__name__ in {
                "ContentFilterFinishReasonError",
                "LengthFinishReasonError",
            }:
                raise VisionParseError("Structured output was not completed") from exc
            raise VisionAPIError("OpenAI model request failed") from exc

        return extract_openai_label(response)

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
