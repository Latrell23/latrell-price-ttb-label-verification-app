import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.vision import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_VISION_MODEL,
    FakeVisionService,
    OpenAIVisionService,
)


SAMPLE_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run OpenAIVisionService against a label image. If no image path is "
            "provided, a sample label image is generated under /tmp."
        )
    )
    parser.add_argument("image_path", nargs="?", help="Path to a label image")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic mock extraction data instead of calling OpenAI",
    )
    parser.add_argument("--model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    image_path = Path(args.image_path) if args.image_path else _create_sample_image()
    service = (
        FakeVisionService()
        if args.mock
        else OpenAIVisionService(model=args.model, timeout_seconds=args.timeout)
    )
    label = service.extract_label(image_path.read_bytes(), _content_type_for(image_path))
    print(json.dumps(label.model_dump(), indent=2, sort_keys=True))
    return 0


def _create_sample_image() -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise SystemExit("Pillow is required to generate the sample image") from exc

    path = Path("/tmp/ttb_sample_label.jpg")
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    font_large = _font(ImageFont, 72)
    font_medium = _font(ImageFont, 44)
    font_small = _font(ImageFont, 30)

    y = 90
    for text, font, spacing in [
        ("ACME ESTATE", font_large, 110),
        ("RED WINE", font_medium, 80),
        ("ALC. 13.5% BY VOL.", font_medium, 80),
        ("750 mL", font_medium, 90),
        ("Produced by Acme Cellars", font_small, 52),
        ("United States", font_small, 80),
    ]:
        _center(draw, text, y, image.width, font)
        y += spacing

    warning_lines = _wrap(SAMPLE_WARNING, 58)
    y += 40
    for line in warning_lines:
        _center(draw, line, y, image.width, font_small)
        y += 42

    image.save(path, format="JPEG", quality=92)
    return path


def _font(image_font_module, size: int):
    try:
        return image_font_module.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return image_font_module.load_default()


def _center(draw, text: str, y: int, width: int, font) -> None:
    bbox = draw.textbbox((0, y), text, font=font)
    x = (width - (bbox[2] - bbox[0])) // 2
    draw.text((x, y), text, fill="black", font=font)


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join([*current, word])
        if current and len(proposed) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _content_type_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
