import base64
import json
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Protocol

from pydantic import ValidationError

from app.verification.models import ExtractedLabel


DEFAULT_VISION_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_IMAGE_EDGE = 2048
DEFAULT_JPEG_QUALITY = 85

VISION_PROMPT = """
Extract TTB alcohol label information from the image.
Return only fields visible in the image.
If a field is missing, obscured, unreadable, or uncertain, return null.
Copy government_warning verbatim exactly as printed, preserving case,
punctuation, internal spacing, line text, and the colon.
If the full government warning is not visible/readable, return
government_warning as null; do not reconstruct the statutory warning from
memory.
Do not infer missing values from general product knowledge.
Set raw_text to the visible label text you can read; use null if no text is
readable.
Set extraction_confidence from 0.0 to 1.0 based on image readability and
extraction certainty.
For valid non-label images, return null label fields, readable raw_text if any,
and low or zero extraction_confidence.
""".strip()


class VisionServiceError(Exception):
    """Base exception for label vision extraction failures."""


class VisionConfigurationError(VisionServiceError):
    """Raised when the real vision service cannot be configured."""


class VisionImageValidationError(VisionServiceError):
    """Raised when image bytes are invalid before any API call."""


class VisionAPIError(VisionServiceError):
    """Raised when the model API request fails or times out."""


class VisionParseError(VisionServiceError):
    """Raised when a completed model response cannot be parsed safely."""


class VisionService(Protocol):
    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Extract structured label fields from image bytes."""


class ResponsesParseProtocol(Protocol):
    def parse(self, **kwargs: Any) -> Any:
        """Subset of the OpenAI Responses parse client used by this service."""


class OpenAIClientProtocol(Protocol):
    responses: ResponsesParseProtocol


class GeminiModelsProtocol(Protocol):
    def generate_content(self, **kwargs: Any) -> Any:
        """Subset of the Gemini generate_content client used by this service."""


class GeminiClientProtocol(Protocol):
    models: GeminiModelsProtocol


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int


class ImagePreprocessor:
    def __init__(
        self,
        max_long_edge: int = DEFAULT_MAX_IMAGE_EDGE,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    ) -> None:
        self.max_long_edge = max_long_edge
        self.jpeg_quality = jpeg_quality

    def process(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ProcessedImage:
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError("Pillow is required for image preprocessing") from exc

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.thumbnail(
                    (self.max_long_edge, self.max_long_edge),
                    Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=self.jpeg_quality,
                    optimize=True,
                )
                return ProcessedImage(
                    data=output.getvalue(),
                    content_type="image/jpeg",
                    width=image.width,
                    height=image.height,
                )
        except UnidentifiedImageError as exc:
            raise VisionImageValidationError("Invalid image bytes") from exc
        except OSError as exc:
            raise VisionImageValidationError("Invalid image bytes") from exc


class OpenAIVisionService:
    def __init__(
        self,
        client: OpenAIClientProtocol | None = None,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_VISION_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key, timeout_seconds)

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        processed = self.preprocessor.process(image_bytes, content_type)
        data_url = _to_data_url(processed.data, processed.content_type)

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

        return _extract_parsed_label(response)

    @staticmethod
    def _build_client(api_key: str | None, timeout_seconds: float) -> OpenAIClientProtocol:
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
            raise VisionConfigurationError("openai is required for OpenAIVisionService") from exc

        return OpenAI(api_key=resolved_api_key, timeout=timeout_seconds)


class GeminiVisionService:
    def __init__(
        self,
        client: GeminiClientProtocol | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_VISION_MODEL
        self.timeout_seconds = timeout_seconds
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.client = client or self._build_client(api_key)

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        processed = self.preprocessor.process(image_bytes, content_type)

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

        return _extract_gemini_label(response)

    @staticmethod
    def _build_client(api_key: str | None) -> GeminiClientProtocol:
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
            raise VisionConfigurationError("google-genai is required for GeminiVisionService") from exc

        return genai.Client(api_key=resolved_api_key)

    @staticmethod
    def _image_part(processed: ProcessedImage) -> Any:
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


class FakeVisionService:
    def __init__(self, label: ExtractedLabel | None = None) -> None:
        self.label = label or ExtractedLabel(
            brand_name="Acme Estate",
            class_type="Red Wine",
            abv="13.5%",
            net_contents="750 mL",
            producer="Acme Cellars",
            country_of_origin="United States",
            government_warning=(
                "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, "
                "WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY "
                "BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF "
                "ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR "
                "OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
            ),
            raw_text="ACME ESTATE RED WINE ALC. 13.5% BY VOL. 750 mL",
            extraction_confidence=0.98,
        )
        self.calls: list[tuple[bytes, str | None]] = []

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        self.calls.append((image_bytes, content_type))
        return self.label


def _to_data_url(image_bytes: bytes, content_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _extract_parsed_label(response: Any) -> ExtractedLabel:
    refusal = _find_refusal(response)
    if refusal:
        raise VisionParseError(f"Vision model refused structured extraction: {refusal}")

    parsed = _get_value(response, "output_parsed")
    if parsed is None:
        parsed = _find_content_parsed(response)
    if parsed is None:
        raise VisionParseError("Vision model response did not include parsed output")

    if isinstance(parsed, ExtractedLabel):
        return parsed
    try:
        return ExtractedLabel.model_validate(parsed)
    except ValidationError as exc:
        raise VisionParseError("Parsed output does not match ExtractedLabel") from exc


def _extract_gemini_label(response: Any) -> ExtractedLabel:
    parsed = _get_value(response, "parsed")
    if parsed is not None:
        if isinstance(parsed, ExtractedLabel):
            return parsed
        try:
            return ExtractedLabel.model_validate(parsed)
        except ValidationError as exc:
            raise VisionParseError("Parsed output does not match ExtractedLabel") from exc

    text = _get_value(response, "text")
    if not text:
        raise VisionParseError("Gemini response did not include text output")

    try:
        decoded = json.loads(text)
        return ExtractedLabel.model_validate(decoded)
    except json.JSONDecodeError as exc:
        raise VisionParseError("Gemini response text was not valid JSON") from exc
    except ValidationError as exc:
        raise VisionParseError("Parsed output does not match ExtractedLabel") from exc


def _find_content_parsed(response: Any) -> Any:
    for output in _iter_collection(_get_value(response, "output")):
        for item in _iter_collection(_get_value(output, "content")):
            parsed = _get_value(item, "parsed")
            if parsed is not None:
                return parsed
    return None


def _find_refusal(response: Any) -> str | None:
    for output in _iter_collection(_get_value(response, "output")):
        for item in _iter_collection(_get_value(output, "content")):
            if _get_value(item, "type") == "refusal":
                refusal = _get_value(item, "refusal")
                return str(refusal or "refusal")
    return None


def _iter_collection(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
