import json
from typing import Any

from pydantic import ValidationError

from app.verification.models import ExtractedLabel
from app.vision.errors import VisionParseError


def extract_openai_label(response: Any) -> ExtractedLabel:
    """Extract and validate an OpenAI structured label response."""
    # Refusals are terminal because they contain no safe parsed label payload.
    refusal = _find_refusal(response)
    if refusal:
        raise VisionParseError(f"Vision model refused structured extraction: {refusal}")

    # Prefer direct parsed output, then fall back to parsed content items.
    parsed = _get_value(response, "output_parsed")
    if parsed is None:
        parsed = _find_content_parsed(response)
    if parsed is None:
        raise VisionParseError("Vision model response did not include parsed output")

    return _validate_extracted_label(parsed)


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


def _find_content_parsed(response: Any) -> Any:
    """Find the first parsed content item in an OpenAI response."""
    for output in _iter_collection(_get_value(response, "output")):
        for item in _iter_collection(_get_value(output, "content")):
            parsed = _get_value(item, "parsed")
            if parsed is not None:
                return parsed

    return None


def _find_refusal(response: Any) -> str | None:
    """Find an OpenAI refusal message when the model declines extraction."""
    for output in _iter_collection(_get_value(response, "output")):
        for item in _iter_collection(_get_value(output, "content")):
            if _get_value(item, "type") == "refusal":
                refusal = _get_value(item, "refusal")
                return str(refusal or "refusal")

    return None


def _iter_collection(value: Any) -> list[Any]:
    """Return a list for optional scalar-or-list provider fields."""
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _get_value(value: Any, key: str) -> Any:
    """Read a value from either a dictionary or object attribute."""
    if isinstance(value, dict):
        return value.get(key)

    return getattr(value, key, None)
