class VisionServiceError(Exception):
    """Base exception for label vision extraction failures."""


class VisionConfigurationError(VisionServiceError):
    """Raised when the real vision service cannot be configured."""


class VisionImageValidationError(VisionServiceError):
    """Raised when image bytes are invalid before any API call."""


class VisionAPIError(VisionServiceError):
    """Raised when the model API request fails or times out."""

    def __init__(self, message: str, *, reason: str = "provider_error") -> None:
        super().__init__(message)
        self.reason = reason


class VisionParseError(VisionServiceError):
    """Raised when a completed model response cannot be parsed safely."""
