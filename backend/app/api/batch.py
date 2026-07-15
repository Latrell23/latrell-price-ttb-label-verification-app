import asyncio
import concurrent.futures
import json
import os
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, TypedDict

from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.errors import (
    error_payload,
    json_response_error,
    vision_exception_error,
)
from app.api.timing import (
    log_batch_stream_complete,
    now_counter,
    now_ms_since,
)
from app.api.validation import read_validated_image, validate_application_fields
from app.responses import error_response
from app.verification import (
    APIError,
    BatchVerificationItem,
    BatchVerificationResponse,
    BatchVerificationSummary,
    verify_label,
)
from app.vision import (
    DEFAULT_TIMEOUT_SECONDS,
    VisionService,
    extract_label_with_timeout,
)


DEFAULT_MAX_BATCH_ITEMS = 5
DEFAULT_MAX_BATCH_CONCURRENCY = 3
APPLICATION_FIELD_NAMES = (
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
)


class PreparedUpload(TypedDict):
    file_name: str | None
    content_type: str | None
    image_bytes: bytes | None
    image_error: APIError | None


def max_batch_concurrency() -> int:
    """Return the configured maximum concurrent batch extractions."""
    try:
        configured = int(
            os.getenv("MAX_BATCH_CONCURRENCY", str(DEFAULT_MAX_BATCH_CONCURRENCY))
        )
    except ValueError:
        return DEFAULT_MAX_BATCH_CONCURRENCY

    return max(1, configured)


def max_batch_items() -> int:
    """Return the configured maximum item count for one batch request."""
    try:
        configured = int(os.getenv("MAX_BATCH_ITEMS", str(DEFAULT_MAX_BATCH_ITEMS)))
    except ValueError:
        return DEFAULT_MAX_BATCH_ITEMS

    return max(1, configured)


def parse_batch_items(
    items: str | None,
) -> tuple[list[dict[str, Any]] | None, JSONResponse | None]:
    """Parse and structurally validate batch metadata."""
    if items is None:
        return None, error_response(
            422,
            "missing_items",
            "The items field is required.",
            [{"field": "items", "message": "Add batch item metadata."}],
        )

    try:
        parsed = json.loads(items)
    except json.JSONDecodeError:
        return None, error_response(
            422,
            "malformed_items",
            "The items field must be valid JSON.",
            [{"field": "items", "message": "Send a JSON array of label metadata."}],
        )

    if not isinstance(parsed, list):
        return None, error_response(
            422,
            "malformed_items",
            "The items field must be a JSON array.",
            [{"field": "items", "message": "Send a JSON array."}],
        )

    if not parsed:
        return None, error_response(
            422,
            "empty_batch",
            "Add at least one label to verify.",
            [{"field": "items", "message": "Add at least one label."}],
        )

    configured_max_batch_items = max_batch_items()
    if len(parsed) > configured_max_batch_items:
        return None, error_response(
            422,
            "too_many_items",
            f"Verify no more than {configured_max_batch_items} labels at once.",
            [
                {
                    "field": "items",
                    "message": f"Maximum is {configured_max_batch_items} labels.",
                }
            ],
        )

    client_ids: set[str] = set()
    image_fields: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            return None, error_response(
                422,
                "malformed_items",
                "Each batch item must be an object.",
                [{"field": f"items[{index}]", "message": "Use an object."}],
            )

        client_id = item.get("client_id")
        image_field = item.get("image_field")
        if not isinstance(client_id, str) or not client_id.strip():
            return None, error_response(
                422,
                "malformed_items",
                "Each batch item needs a client_id.",
                [
                    {
                        "field": f"items[{index}].client_id",
                        "message": "Add a client_id.",
                    }
                ],
            )
        if not isinstance(image_field, str) or not image_field.strip():
            return None, error_response(
                422,
                "malformed_items",
                "Each batch item needs an image_field.",
                [
                    {
                        "field": f"items[{index}].image_field",
                        "message": "Add an image_field.",
                    }
                ],
            )

        client_id = client_id.strip()
        image_field = image_field.strip()
        if client_id in client_ids:
            return None, error_response(
                422,
                "duplicate_client_id",
                "Each batch item must have a unique client_id.",
                [{"field": "client_id", "message": f"Duplicate: {client_id}."}],
            )
        if image_field in image_fields:
            return None, error_response(
                422,
                "duplicate_image_field",
                "Each batch item must have a unique image_field.",
                [{"field": "image_field", "message": f"Duplicate: {image_field}."}],
            )

        client_ids.add(client_id)
        image_fields.add(image_field)
        normalized_items.append(
            item | {"client_id": client_id, "image_field": image_field}
        )

    return normalized_items, None


def collect_batch_uploads(
    batch_items: list[dict[str, Any]],
    form: Mapping[str, object],
) -> tuple[dict[str, StarletteUploadFile] | None, JSONResponse | None]:
    """Match each batch item to an uploaded file field."""
    uploads: dict[str, StarletteUploadFile] = {}
    missing_uploads: list[dict[str, str]] = []
    for item in batch_items:
        upload = form.get(item["image_field"])
        if not isinstance(upload, StarletteUploadFile):
            missing_uploads.append(
                {
                    "field": item["image_field"],
                    "message": "Upload one label image for this item.",
                }
            )
        else:
            uploads[item["image_field"]] = upload

    if missing_uploads:
        return None, error_response(
            422,
            "missing_upload_fields",
            "One or more batch image uploads are missing.",
            missing_uploads,
        )

    return uploads, None


async def prepare_batch_uploads(
    batch_items: list[dict[str, Any]],
    uploads: Mapping[str, StarletteUploadFile],
) -> dict[str, PreparedUpload]:
    """Read batch upload bytes before the streaming response starts."""
    prepared_uploads: dict[str, PreparedUpload] = {}
    for item in batch_items:
        upload = uploads[item["image_field"]]
        image_bytes, image_error = await read_validated_image(upload)
        prepared_uploads[item["image_field"]] = {
            "file_name": upload.filename,
            "content_type": upload.content_type,
            "image_bytes": image_bytes,
            "image_error": (
                json_response_error(image_error) if image_error is not None else None
            ),
        }

    return prepared_uploads


async def verify_batch_item(
    *,
    item: dict[str, Any],
    upload: StarletteUploadFile,
    vision_service: VisionService,
    semaphore: asyncio.Semaphore,
    executor: concurrent.futures.ThreadPoolExecutor,
) -> BatchVerificationItem:
    """Validate and verify one batch item without affecting other items."""
    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
    application_data, field_error = validate_application_fields(
        {field: item.get(field) for field in APPLICATION_FIELD_NAMES}
    )
    if field_error is not None:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=upload.filename,
            status="failed",
            result=None,
            error=json_response_error(field_error),
        )

    image_bytes, image_error = await read_validated_image(upload)
    return await verify_batch_item_data(
        item=item,
        file_name=upload.filename,
        image_bytes=image_bytes,
        image_error=json_response_error(image_error) if image_error is not None else None,
        content_type=upload.content_type,
        vision_service=vision_service,
        semaphore=semaphore,
        executor=executor,
        deadline=deadline,
    )


async def verify_batch_item_data(
    *,
    item: dict[str, Any],
    file_name: str | None,
    image_bytes: bytes | None,
    image_error: APIError | None,
    content_type: str | None,
    vision_service: VisionService,
    semaphore: asyncio.Semaphore,
    executor: concurrent.futures.ThreadPoolExecutor,
    deadline: float | None = None,
) -> BatchVerificationItem:
    """Validate and verify one batch item from already-read upload bytes."""
    deadline = (
        time.monotonic() + DEFAULT_TIMEOUT_SECONDS if deadline is None else deadline
    )
    application_data, field_error = validate_application_fields(
        {field: item.get(field) for field in APPLICATION_FIELD_NAMES}
    )
    if field_error is not None:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=file_name,
            status="failed",
            result=None,
            error=json_response_error(field_error),
        )

    if image_error is not None or image_bytes is None:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=file_name,
            status="failed",
            result=None,
            error=image_error
            or error_payload(
                "invalid_image",
                "The uploaded file is not a readable image.",
                [{"field": "image", "message": "Upload a readable image file."}],
            ),
        )

    started_at = now_counter()
    try:
        async with semaphore:
            extracted_label = await extract_label_with_timeout(
                vision_service,
                image_bytes,
                content_type,
                executor,
                deadline=deadline,
            )
        result = verify_label(application_data, extracted_label).model_copy(
            update={"latency_ms": now_ms_since(started_at)}
        )
    except Exception as exception:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=file_name,
            status="failed",
            result=None,
            error=vision_exception_error(exception),
        )

    return BatchVerificationItem(
        client_id=item["client_id"],
        file_name=file_name,
        status="completed",
        result=result,
        error=None,
    )


async def run_batch_verification(
    *,
    batch_items: list[dict[str, Any]],
    uploads: Mapping[str, StarletteUploadFile],
    vision_service: VisionService,
) -> list[BatchVerificationItem]:
    configured_max_concurrency = max_batch_concurrency()
    semaphore = asyncio.Semaphore(configured_max_concurrency)
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=configured_max_concurrency
    )
    try:
        return await asyncio.gather(
            *[
                verify_batch_item(
                    item=item,
                    upload=uploads[item["image_field"]],
                    vision_service=vision_service,
                    semaphore=semaphore,
                    executor=executor,
                )
                for item in batch_items
            ]
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def build_batch_response(
    *,
    results: list[BatchVerificationItem],
    started_at: float,
) -> BatchVerificationResponse:
    passed, needs_review, completed, failed = summarize_batch_results(results)
    return BatchVerificationResponse(
        items=results,
        summary=BatchVerificationSummary(
            passed=passed,
            needs_review=needs_review,
            completed=completed,
            failed=failed,
            total=len(results),
        ),
        latency_ms=now_ms_since(started_at),
    )


def summarize_batch_results(
    results: list[BatchVerificationItem],
) -> tuple[int, int, int, int]:
    passed = sum(
        item.status == "completed"
        and item.result is not None
        and item.result.overall_verdict == "APPROVED"
        for item in results
    )
    needs_review = sum(
        item.status == "completed"
        and item.result is not None
        and item.result.overall_verdict == "NEEDS_REVIEW"
        for item in results
    )
    completed = passed + needs_review
    failed = sum(item.status == "failed" for item in results)
    return passed, needs_review, completed, failed


async def stream_batch_results(
    *,
    batch_items: list[dict[str, Any]],
    prepared_uploads: Mapping[str, PreparedUpload],
    vision_service: VisionService,
    started_at: float,
) -> AsyncIterator[str]:
    configured_max_concurrency = max_batch_concurrency()
    semaphore = asyncio.Semaphore(configured_max_concurrency)
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=configured_max_concurrency
    )
    completed_items = 0
    failed_items = 0
    item_results: list[BatchVerificationItem] = []

    tasks = []
    for item in batch_items:
        prepared_upload = prepared_uploads[item["image_field"]]
        tasks.append(
            asyncio.create_task(
                verify_batch_item_data(
                    item=item,
                    file_name=prepared_upload["file_name"],
                    image_bytes=prepared_upload["image_bytes"],
                    image_error=prepared_upload["image_error"],
                    content_type=prepared_upload["content_type"],
                    vision_service=vision_service,
                    semaphore=semaphore,
                    executor=executor,
                )
            )
        )

    try:
        for completed_task in asyncio.as_completed(tasks):
            item_result = await completed_task
            item_results.append(item_result)

            if item_result.status == "completed":
                completed_items += 1
            else:
                failed_items += 1

            yield (
                json.dumps(
                    {
                        "type": "item",
                        "item": item_result.model_dump(mode="json"),
                        "progress": {
                            "completed": len(item_results),
                            "total": len(batch_items),
                        },
                    }
                )
                + "\n"
            )

        passed, needs_review, _, _ = summarize_batch_results(item_results)
        summary = BatchVerificationSummary(
            passed=passed,
            needs_review=needs_review,
            completed=passed + needs_review,
            failed=failed_items,
            total=len(item_results),
        )
        latency_ms = now_ms_since(started_at)
        log_batch_stream_complete(
            started_at=started_at,
            item_count=len(item_results),
            completed=completed_items,
            failed=failed_items,
        )
        yield (
            json.dumps(
                {
                    "type": "complete",
                    "summary": summary.model_dump(mode="json"),
                    "latency_ms": latency_ms,
                }
            )
            + "\n"
        )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
