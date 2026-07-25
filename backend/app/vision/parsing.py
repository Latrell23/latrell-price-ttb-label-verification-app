from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.errors import VisionParseError


NULL_STRING_VALUES = {"", "null", "none", "n/a", "not found"}
NULLABLE_TEXT_FIELDS = (
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
    "raw_text",
)


def extract_openai_label(response: Any) -> ExtractedLabel:
    """Extract and validate an OpenAI structured label response."""
    parsed = _get_value(response, "output_parsed")
    if parsed is None:
        raise VisionParseError("OpenAI response did not include structured output")

    return _validate_extracted_label(parsed)


def _validate_extracted_label(parsed: Any) -> ExtractedLabel:
    """Validate parsed provider output against the ExtractedLabel schema."""
    if isinstance(parsed, ExtractedLabel):
        return _normalize_extracted_label(parsed)

    try:
        return _normalize_extracted_label(ExtractedLabel.model_validate(parsed))
    except ValidationError as exc:
        raise VisionParseError("Parsed output does not match ExtractedLabel") from exc


def _get_value(value: Any, key: str) -> Any:
    """Read a value from either a dictionary or object attribute."""
    if isinstance(value, dict):
        return value.get(key)

    return getattr(value, key, None)


def _normalize_extracted_label(label: ExtractedLabel) -> ExtractedLabel:
    """Normalize model-emitted null-like strings into missing values."""
    updates: dict[str, str | None] = {}
    for field in NULLABLE_TEXT_FIELDS:
        value = getattr(label, field)
        if isinstance(value, str) and value.strip().casefold() in NULL_STRING_VALUES:
            updates[field] = None

    return label.model_copy(update=updates) if updates else label
