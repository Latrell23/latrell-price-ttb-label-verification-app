from typing import Any, Protocol

from app.verification.models import ExtractedLabel


class VisionService(Protocol):
    """Protocol for services that extract structured label fields from images."""

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Extract structured label fields from image bytes."""


class ResponsesParseProtocol(Protocol):
    """Protocol for the OpenAI Responses parse client used by this service."""

    def parse(self, **kwargs: Any) -> Any:
        """Parse a structured OpenAI response request."""


class OpenAIClientProtocol(Protocol):
    """Protocol for the subset of the OpenAI client used by this service."""

    responses: ResponsesParseProtocol


class GeminiModelsProtocol(Protocol):
    """Protocol for the Gemini models client used by this service."""

    def generate_content(self, **kwargs: Any) -> Any:
        """Generate Gemini content from a structured request."""


class GeminiClientProtocol(Protocol):
    """Protocol for the subset of the Gemini client used by this service."""

    models: GeminiModelsProtocol
