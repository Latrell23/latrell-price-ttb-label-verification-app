import asyncio
import concurrent.futures
import json
import os
import time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.api.errors import error_payload, vision_exception_error
from app.api.timing import now_counter, now_ms_since
from app.verification import (
    APIError,
    ApplicationData,
    ReviewVerificationItem,
    ReviewVerificationResponse,
    ReviewVerificationSummary,
    verify_label,
)
from app.vision import DEFAULT_TIMEOUT_SECONDS, VisionService, extract_label_with_timeout


REVIEW_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
REVIEW_LABELS_PATH = REVIEW_FIXTURE_DIR / "labels.json"
REVIEW_IMAGE_DIR = REVIEW_FIXTURE_DIR / "images"
DEFAULT_REVIEW_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_REVIEW_CONCURRENCY = 3


class ReviewLabelPublic(BaseModel):
    """Reviewer-facing label metadata and expected application JSON."""

    id: str
    title: str
    image_url: str
    expected: ApplicationData


class ReviewLabel(BaseModel):
    """Backend-owned simulated label fixture."""

    id: str
    title: str
    image_file: str
    expected: ApplicationData

    @property
    def image_path(self) -> Path:
        return REVIEW_IMAGE_DIR / self.image_file

    def to_public(self) -> ReviewLabelPublic:
        return ReviewLabelPublic(
            id=self.id,
            title=self.title,
            image_url=f"/review/assets/{self.image_file}",
            expected=self.expected,
        )


class ReviewLabelList(BaseModel):
    """Reviewer queue response."""

    items: list[ReviewLabelPublic]


def list_review_labels() -> list[ReviewLabel]:
    """Return the configured simulated review queue."""
    return list(_load_review_labels())


def get_review_label(label_id: str) -> ReviewLabel | None:
    """Return one simulated review label by ID."""
    return next(
        (label for label in _load_review_labels() if label.id == label_id),
        None,
    )


def review_timeout_seconds() -> float:
    """Return the per-label AI extraction budget for reviewer fixtures."""
    try:
        configured = float(
            os.getenv("REVIEW_TIMEOUT_SECONDS", str(DEFAULT_REVIEW_TIMEOUT_SECONDS))
        )
    except ValueError:
        return DEFAULT_REVIEW_TIMEOUT_SECONDS

    return max(DEFAULT_TIMEOUT_SECONDS, configured)


def max_review_concurrency() -> int:
    """Return the maximum number of concurrent AI reviews."""
    try:
        configured = int(
            os.getenv(
                "MAX_REVIEW_CONCURRENCY",
                str(DEFAULT_MAX_REVIEW_CONCURRENCY),
            )
        )
    except ValueError:
        return DEFAULT_MAX_REVIEW_CONCURRENCY

    return max(1, configured)


async def verify_review_label(
    *,
    label: ReviewLabel,
    vision_service: VisionService,
) -> ReviewVerificationItem:
    """Verify one backend-owned review label image against its JSON fixture."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return await _verify_review_label_with_executor(
            label=label,
            vision_service=vision_service,
            executor=executor,
            deadline=time.monotonic() + review_timeout_seconds(),
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


async def verify_review_queue(
    *,
    labels: list[ReviewLabel],
    vision_service: VisionService,
) -> ReviewVerificationResponse:
    """Verify the full simulated review queue concurrently."""
    started_at = now_counter()
    configured_max_concurrency = max_review_concurrency()
    semaphore = asyncio.Semaphore(configured_max_concurrency)
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=configured_max_concurrency
    )
    try:
        results = await asyncio.gather(
            *[
                _verify_review_label_with_executor(
                    label=label,
                    vision_service=vision_service,
                    executor=executor,
                    semaphore=semaphore,
                    deadline=time.monotonic() + review_timeout_seconds(),
                )
                for label in labels
            ]
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    passed = sum(
        item.status == "completed"
        and item.result is not None
        and item.result.overall_verdict == "APPROVED"
        for item in results
    )
    completed = sum(item.status == "completed" for item in results)
    failed = len(results) - completed
    return ReviewVerificationResponse(
        items=results,
        summary=ReviewVerificationSummary(
            passed=passed,
            needs_review=completed - passed,
            completed=completed,
            failed=failed,
            total=len(results),
        ),
        latency_ms=now_ms_since(started_at),
    )


@lru_cache(maxsize=1)
def _load_review_labels() -> tuple[ReviewLabel, ...]:
    """Load and validate simulated review labels from fixture JSON."""
    try:
        raw_labels = json.loads(REVIEW_LABELS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Review label fixtures could not be loaded") from exc

    if not isinstance(raw_labels, list):
        raise RuntimeError("Review label fixtures must be a JSON array")

    labels: list[ReviewLabel] = []
    seen_ids: set[str] = set()
    for raw_label in raw_labels:
        try:
            label = ReviewLabel.model_validate(raw_label)
        except ValidationError as exc:
            raise RuntimeError("Review label fixture is malformed") from exc
        if label.id in seen_ids:
            raise RuntimeError(f"Duplicate review label id: {label.id}")
        if not label.image_path.is_file():
            raise RuntimeError(f"Review label image is missing: {label.image_file}")
        seen_ids.add(label.id)
        labels.append(label)

    return tuple(labels)


async def _verify_review_label_with_executor(
    *,
    label: ReviewLabel,
    vision_service: VisionService,
    executor: concurrent.futures.ThreadPoolExecutor,
    deadline: float,
    semaphore: asyncio.Semaphore | None = None,
) -> ReviewVerificationItem:
    """Run the shared vision and comparison flow for one fixture label."""
    image_bytes, image_error = _read_review_image(label)
    if image_error is not None:
        return ReviewVerificationItem(
            client_id=label.id,
            file_name=label.image_file,
            status="failed",
            result=None,
            error=image_error,
        )

    started_at = now_counter()
    try:
        if semaphore is None:
            extracted_label = await extract_label_with_timeout(
                vision_service,
                image_bytes,
                "image/jpeg",
                executor,
                deadline=deadline,
            )
        else:
            async with semaphore:
                extracted_label = await extract_label_with_timeout(
                    vision_service,
                    image_bytes,
                    "image/jpeg",
                    executor,
                    deadline=deadline,
                )

        result = verify_label(label.expected, extracted_label).model_copy(
            update={"latency_ms": now_ms_since(started_at)}
        )
        return ReviewVerificationItem(
            client_id=label.id,
            file_name=label.image_file,
            status="completed",
            result=result,
            error=None,
        )
    except Exception as exception:
        return ReviewVerificationItem(
            client_id=label.id,
            file_name=label.image_file,
            status="failed",
            result=None,
            error=vision_exception_error(exception),
        )


def _read_review_image(label: ReviewLabel) -> tuple[bytes, APIError | None]:
    try:
        return label.image_path.read_bytes(), None
    except OSError:
        return b"", error_payload(
            "review_image_unavailable",
            "The simulated label image could not be loaded.",
            [{"field": "image", "message": "Review fixture image is unavailable."}],
        )
