from typing import Protocol

from app.verification.models import ExtractedLabel


class VisionService(Protocol):
    """Protocol for services that extract structured label fields from images."""

    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
        *,
        deadline: float | None = None,
    ) -> ExtractedLabel:
        """Extract structured label fields from image bytes."""


class OpenAIResponsesProtocol(Protocol):
    """Protocol for the OpenAI Responses client used by this service."""

    def parse(self, **kwargs: object) -> object:
        """Create and parse an OpenAI response from a structured request."""


class OpenAIClientProtocol(Protocol):
    """Protocol for the subset of the OpenAI client used by this service."""

    responses: OpenAIResponsesProtocol
