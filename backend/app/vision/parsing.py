import json
from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.errors import VisionParseError


def extract_gemini_label(response: Any) -> ExtractedLabel:
    """Extract and validate a Gemini structured label response."""
    # Prefer SDK-parsed output when available.
    parsed = _get_value(response, "parsed")
    if parsed is not None:
        return _validate_extracted_label(parsed)

    # Fall back to JSON text emitted by Gemini.
    text = _get_value(response, "text")
    if not text:
        raise VisionParseError("Gemini response did not include text output")

    try:
        decoded = json.loads(text)
        return _validate_extracted_label(decoded)
    except json.JSONDecodeError as exc:
        raise VisionParseError("Gemini response text was not valid JSON") from exc


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
