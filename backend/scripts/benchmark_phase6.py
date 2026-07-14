import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.verification import ApplicationData, verify_label
from app.vision import (
    DEFAULT_MAX_IMAGE_EDGE,
    DEFAULT_TIMEOUT_SECONDS,
    FakeVisionService,
    OpenAIVisionService,
    ImagePreprocessor,
    VisionServiceError,
    extract_label_with_timeout_sync,
)


SAMPLE_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)

APPLICATION = ApplicationData(
    brand_name="Acme Estate",
    class_type="Red Wine",
    abv="13.5%",
    net_contents="750 mL",
    producer="Acme Cellars",
    country_of_origin="United States",
    government_warning=SAMPLE_WARNING,
)


@dataclass(frozen=True)
class Fixture:
    name: str
    path: Path
    content_type: str
    expected_behavior: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Phase 6 single-label benchmark with OpenAI or the local "
            "fake provider."
        )
    )
    parser.add_argument("--fixture-dir", type=Path, default=Path("/tmp/ttb-phase6-fixtures"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mock", action="store_true", help="Use FakeVisionService.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-edge", type=int, default=DEFAULT_MAX_IMAGE_EDGE)
    parser.add_argument("--jpeg-quality", type=int, default=78)
    parser.add_argument("--jsonl", type=Path, help="Optional path for per-run JSONL output.")
    args = parser.parse_args()

    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    fixtures = ensure_fixtures(args.fixture_dir)
    preprocessor = ImagePreprocessor(
        max_long_edge=args.max_edge,
        jpeg_quality=args.jpeg_quality,
    )
    service = (
        FakeVisionService()
        if args.mock
        else OpenAIVisionService(
            timeout_seconds=args.timeout,
            preprocessor=preprocessor,
        )
    )

    records: list[dict[str, Any]] = []
    jsonl_file = args.jsonl.open("w", encoding="utf-8") if args.jsonl else None
    try:
        for run_index in range(args.runs):
            for fixture in fixtures:
                record = benchmark_fixture(
                    fixture=fixture,
                    run_index=run_index,
                    service=service,
                    preprocessor=preprocessor,
                    config={
                        "provider": "fake" if args.mock else "openai",
                        "model": "fake" if args.mock else service.model,
                        "timeout_seconds": args.timeout,
                        "max_edge": args.max_edge,
                        "jpeg_quality": args.jpeg_quality,
                    },
                )
                records.append(record)
                if jsonl_file is not None:
                    jsonl_file.write(json.dumps(record, sort_keys=True) + "\n")
    finally:
        if jsonl_file is not None:
            jsonl_file.close()

    print(json.dumps(summary(records), indent=2, sort_keys=True))
    return 0


def benchmark_fixture(
    *,
    fixture: Fixture,
    run_index: int,
    service: Any,
    preprocessor: ImagePreprocessor,
    config: dict[str, Any],
) -> dict[str, Any]:
    image_bytes = fixture.path.read_bytes()
    record: dict[str, Any] = {
        "fixture": fixture.name,
        "run_index": run_index,
        "expected_behavior": fixture.expected_behavior,
        "original_image_bytes": len(image_bytes),
        "content_type": fixture.content_type,
        "config": config,
        "http_status": None,
        "error_code": None,
        "overall_verdict": None,
        "null_field_count": None,
        "extraction_confidence": None,
    }

    preprocess_started = time.perf_counter()
    try:
        processed = preprocessor.process(image_bytes, fixture.content_type)
        record.update(
            {
                "processed_image_bytes": len(processed.data),
                "processed_width": processed.width,
                "processed_height": processed.height,
                "preprocessing_latency_ms": elapsed_ms(preprocess_started),
            }
        )
    except Exception:
        record.update(
            {
                "processed_image_bytes": None,
                "processed_width": None,
                "processed_height": None,
                "preprocessing_latency_ms": elapsed_ms(preprocess_started),
                "http_status": 400,
                "error_code": "invalid_image",
            }
        )
        return record

    model_started = time.perf_counter()
    try:
        extracted = extract_label_with_timeout_sync(
            service,
            image_bytes,
            fixture.content_type,
            config["timeout_seconds"],
        )
        model_latency_ms = elapsed_ms(model_started)
        result = verify_label(APPLICATION, extracted)
        record.update(
            {
                "model_request_latency_ms": model_latency_ms,
                "endpoint_total_latency_ms": record["preprocessing_latency_ms"]
                + model_latency_ms
                + result.latency_ms,
                "http_status": 200,
                "overall_verdict": result.overall_verdict,
                "null_field_count": null_field_count(extracted.model_dump()),
                "extraction_confidence": extracted.extraction_confidence,
            }
        )
    except VisionServiceError as exc:
        record.update(
            {
                "model_request_latency_ms": elapsed_ms(model_started),
                "endpoint_total_latency_ms": elapsed_ms(model_started)
                + record["preprocessing_latency_ms"],
                "http_status": 502,
                "error_code": exc.__class__.__name__,
            }
        )

    return record


def ensure_fixtures(fixture_dir: Path) -> list[Fixture]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    create_label_image(fixture_dir / "clear-label.jpg")
    create_label_image(fixture_dir / "phone-photo-large.jpg", size=(3200, 4200), rotate=True)
    create_label_image(fixture_dir / "oversized-label.jpg", size=(4200, 5200))
    create_label_image(fixture_dir / "blurry-low-light.jpg", blur=True, low_light=True)
    create_label_image(fixture_dir / "cropped-warning.jpg", crop_warning=True)
    create_non_label_image(fixture_dir / "non-label.jpg")
    (fixture_dir / "corrupt-image.jpg").write_bytes(b"not a readable image")

    return [
        Fixture("clear-label", fixture_dir / "clear-label.jpg", "image/jpeg", "approved"),
        Fixture(
            "phone-photo-large",
            fixture_dir / "phone-photo-large.jpg",
            "image/jpeg",
            "approved",
        ),
        Fixture(
            "oversized-label",
            fixture_dir / "oversized-label.jpg",
            "image/jpeg",
            "approved",
        ),
        Fixture(
            "blurry-low-light",
            fixture_dir / "blurry-low-light.jpg",
            "image/jpeg",
            "needs_review",
        ),
        Fixture(
            "cropped-warning",
            fixture_dir / "cropped-warning.jpg",
            "image/jpeg",
            "needs_review",
        ),
        Fixture("non-label", fixture_dir / "non-label.jpg", "image/jpeg", "needs_review"),
        Fixture(
            "corrupt-image",
            fixture_dir / "corrupt-image.jpg",
            "image/jpeg",
            "invalid_image",
        ),
    ]


def create_label_image(
    path: Path,
    *,
    size: tuple[int, int] = (1200, 1600),
    rotate: bool = False,
    blur: bool = False,
    low_light: bool = False,
    crop_warning: bool = False,
) -> None:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    image = Image.new("RGB", size, "#f8fafc")
    draw = ImageDraw.Draw(image)
    font_large = font(ImageFont, max(36, size[0] // 17))
    font_medium = font(ImageFont, max(26, size[0] // 27))
    font_small = font(ImageFont, max(18, size[0] // 42))

    y = int(size[1] * 0.06)
    for text, selected_font, spacing in [
        ("ACME ESTATE", font_large, int(size[1] * 0.08)),
        ("RED WINE", font_medium, int(size[1] * 0.055)),
        ("ALC. 13.5% BY VOL.", font_medium, int(size[1] * 0.055)),
        ("750 mL", font_medium, int(size[1] * 0.065)),
        ("Produced by Acme Cellars", font_small, int(size[1] * 0.045)),
        ("United States", font_small, int(size[1] * 0.065)),
    ]:
        center(draw, text, y, size[0], selected_font)
        y += spacing

    if not crop_warning:
        for line in wrap(SAMPLE_WARNING, 58):
            center(draw, line, y, size[0], font_small)
            y += int(size[1] * 0.032)

    if rotate:
        image = image.rotate(3, fillcolor="#f8fafc")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(radius=1.7))
    if low_light:
        image = ImageEnhance.Brightness(image).enhance(0.48)

    image.save(path, format="JPEG", quality=92)


def create_non_label_image(path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 900), "#dbeafe")
    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 180, 1040, 720), outline="#2563eb", width=8)
    draw.text((240, 390), "Warehouse receiving photo", fill="#1e3a8a")
    image.save(path, format="JPEG", quality=92)


def font(image_font_module: Any, size: int) -> Any:
    try:
        return image_font_module.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return image_font_module.load_default()


def center(draw: Any, text: str, y: int, width: int, selected_font: Any) -> None:
    bbox = draw.textbbox((0, y), text, font=selected_font)
    x = (width - (bbox[2] - bbox[0])) // 2
    draw.text((x, y), text, fill="#111827", font=selected_font)


def wrap(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        proposed = " ".join([*current, word])
        if current and len(proposed) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def null_field_count(label: dict[str, Any]) -> int:
    fields = [
        "brand_name",
        "class_type",
        "abv",
        "net_contents",
        "producer",
        "country_of_origin",
        "government_warning",
    ]
    return sum(label.get(field) is None for field in fields)


def elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return ordered[index]


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = [record["endpoint_total_latency_ms"] for record in records if record.get("endpoint_total_latency_ms") is not None]
    preprocessing = [record["preprocessing_latency_ms"] for record in records if record.get("preprocessing_latency_ms") is not None]
    model = [record["model_request_latency_ms"] for record in records if record.get("model_request_latency_ms") is not None]
    return {
        "run_count": len(records),
        "targets": {
            "warm_single_label_p50_ms": 3000,
            "warm_single_label_p95_ms": 4500,
            "warm_single_label_max_ms": 5000,
            "preprocessing_p95_ms": 350,
            "model_call_p95_ms": 4000,
        },
        "endpoint_total_latency_ms": latency_summary(totals),
        "preprocessing_latency_ms": latency_summary(preprocessing),
        "model_request_latency_ms": latency_summary(model),
        "status_counts": count_by(records, "http_status"),
        "verdict_counts": count_by(records, "overall_verdict"),
        "error_counts": count_by(records, "error_code"),
    }


def latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": statistics.median(values) if values else None,
        "p95": percentile(values, 95),
        "max": max(values) if values else None,
    }


def count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(key)
        label = "none" if value is None else str(value)
        counts[label] = counts.get(label, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
