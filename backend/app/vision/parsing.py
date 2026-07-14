from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.errors import VisionParseError


def extract_openai_label(response: Any) -> ExtractedLabel:
    """Extract and validate an OpenAI structured label response."""
    parsed = _get_value(response, "output_parsed")
    if parsed is None:
        raise VisionParseError("OpenAI response did not include structured output")

    return _validate_extracted_label(parsed)


def _validate_extracted_label(parsed: Any) -> ExtractedLabel:
    """Validate parsed provider output against the ExtractedLabel schema."""
    if isinstance(parsed, ExtractedLabel):
        return parsed

    try:
        return ExtractedLabel.model_validate(parsed)
    except ValidationError as exc:
        raise VisionParseError("Parsed output does not match ExtractedLabel") from exc


def _get_value(value: Any, key: str) -> Any:
    """Read a value from either a dictionary or object attribute."""
    if isinstance(value, dict):
        return value.get(key)

    return getattr(value, key, None)
