from dataclasses import dataclass
from io import BytesIO

from app.vision.constants import DEFAULT_JPEG_QUALITY, DEFAULT_MAX_IMAGE_EDGE
from app.vision.errors import VisionConfigurationError, VisionImageValidationError


@dataclass(frozen=True)
class ProcessedImage:
    """JPEG-normalized image bytes and dimensions ready for model input."""

    data: bytes
    content_type: str
    width: int
    height: int


class ImagePreprocessor:
    """Convert uploaded images into bounded JPEG payloads for vision models."""

    def __init__(
        self,
        max_long_edge: int = DEFAULT_MAX_IMAGE_EDGE,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    ) -> None:
        """Store image size and quality limits for preprocessing."""
        self.max_long_edge = max_long_edge
        self.jpeg_quality = jpeg_quality

    def process(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ProcessedImage:
        """Validate, orient, resize, and encode image bytes as JPEG."""
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionConfigurationError(
                "Pillow is required for image preprocessing"
            ) from exc

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                # Load and normalize orientation before resizing.
                image.load()
                image = ImageOps.exif_transpose(image)

                # Convert all model inputs to RGB JPEG.
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.thumbnail(
                    (self.max_long_edge, self.max_long_edge),
                    Image.Resampling.LANCZOS,
                )

                # Save the bounded image payload for provider requests.
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
