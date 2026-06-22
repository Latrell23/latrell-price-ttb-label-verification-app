import asyncio
import concurrent.futures
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.responses import error_response
from app.routes.validation import read_validated_image, validate_application_fields
from app.verification import (
    APIError,
    BatchVerificationItem,
    BatchVerificationResponse,
    BatchVerificationSummary,
    ExtractedLabel,
    VerificationResult,
    verify_label,
)
from app.vision import (
    GeminiVisionService,
    VisionAPIError,
    VisionConfigurationError,
    VisionImageValidationError,
    VisionParseError,
    VisionService,
)


LOGGER = logging.getLogger("app.main")
LATENCY_BUDGET_MS = 5000.0
MAX_BATCH_ITEMS = 5
DEFAULT_MAX_BATCH_CONCURRENCY = 3
VisionServiceDependency = VisionService | Callable[[], VisionService]
APPLICATION_FIELD_NAMES = (
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
)

router = APIRouter()


def get_vision_service() -> Callable[[], VisionService]:
    """Return the default production vision service factory."""
    return GeminiVisionService


def resolve_vision_service(
    vision_service: VisionServiceDependency,
) -> VisionService:
    """Resolve a vision dependency from an instance, class, or callable factory."""
    if isinstance(vision_service, type):
        return vision_service()

    if hasattr(vision_service, "extract_label"):
        return vision_service

    return vision_service()


def _now_ms_since(started_at: float) -> float:
    """Return elapsed milliseconds from the shared application clock."""
    from app import main as main_module

    return (main_module.perf_counter() - started_at) * 1000


def _now_counter() -> float:
    """Return the shared application clock for request timing."""
    from app import main as main_module

    return main_module.perf_counter()


def _max_batch_concurrency() -> int:
    """Return the configured maximum concurrent batch extractions."""
    try:
        configured = int(
            os.getenv("MAX_BATCH_CONCURRENCY", str(DEFAULT_MAX_BATCH_CONCURRENCY))
        )
    except ValueError:
        return DEFAULT_MAX_BATCH_CONCURRENCY

    return max(1, configured)


def _error_payload(
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> APIError:
    """Build the inner API error shape used by failed batch items."""
    return APIError(code=code, message=message, details=details or [])


def _json_response_error(response: JSONResponse) -> APIError:
    """Convert an existing error response into the batch item error shape."""
    body = json.loads(response.body)
    error = body.get("error", {})
    return _error_payload(
        str(error.get("code", "internal_error")),
        str(error.get("message", "An unexpected error occurred.")),
        error.get("details", []),
    )


def _vision_exception_error(exception: Exception) -> APIError:
    """Map vision exceptions to the same public error codes as /verify."""
    if isinstance(exception, VisionImageValidationError):
        return _error_payload(
            "invalid_image",
            "The uploaded file is not a readable image.",
            [{"field": "image", "message": "Upload a readable image file."}],
        )
    if isinstance(exception, VisionConfigurationError):
        return _error_payload(
            "vision_not_configured",
            "Vision service is not configured.",
        )
    if isinstance(exception, VisionAPIError):
        return _error_payload(
            "vision_extraction_failed",
            "Vision extraction failed. Please try again.",
        )
    if isinstance(exception, VisionParseError):
        return _error_payload(
            "vision_result_unreadable",
            "Vision extraction returned an unreadable result.",
        )

    LOGGER.exception("Unexpected /verify/batch item failure")
    return _error_payload(
        "internal_error",
        "An unexpected error occurred while verifying the label.",
    )


def _parse_batch_items(
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

    if len(parsed) > MAX_BATCH_ITEMS:
        return None, error_response(
            422,
            "too_many_items",
            f"Verify no more than {MAX_BATCH_ITEMS} labels at once.",
            [{"field": "items", "message": f"Maximum is {MAX_BATCH_ITEMS} labels."}],
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


async def _verify_batch_item(
    *,
    item: dict[str, Any],
    upload: UploadFile,
    vision_service: VisionService,
    semaphore: asyncio.Semaphore,
    executor: concurrent.futures.ThreadPoolExecutor,
) -> BatchVerificationItem:
    """Validate and verify one batch item without affecting other items."""
    application_data, field_error = validate_application_fields(
        {field: item.get(field) for field in APPLICATION_FIELD_NAMES}
    )
    if field_error is not None:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=upload.filename,
            status="failed",
            result=None,
            error=_json_response_error(field_error),
        )

    image_bytes, image_error = await read_validated_image(upload)
    if image_error is not None:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=upload.filename,
            status="failed",
            result=None,
            error=_json_response_error(image_error),
        )

    started_at = _now_counter()
    try:
        async with semaphore:
            extracted_label = await _extract_label_in_thread(
                vision_service,
                image_bytes,
                upload.content_type,
                executor,
            )
        result = verify_label(application_data, extracted_label).model_copy(
            update={"latency_ms": _now_ms_since(started_at)}
        )
    except Exception as exception:
        return BatchVerificationItem(
            client_id=item["client_id"],
            file_name=upload.filename,
            status="failed",
            result=None,
            error=_vision_exception_error(exception),
        )

    return BatchVerificationItem(
        client_id=item["client_id"],
        file_name=upload.filename,
        status="completed",
        result=result,
        error=None,
    )


async def _extract_label_in_thread(
    vision_service: VisionService,
    image_bytes: bytes,
    content_type: str | None,
    executor: concurrent.futures.ThreadPoolExecutor,
) -> ExtractedLabel:
    """Run blocking extraction in a request-scoped worker thread."""
    future = executor.submit(vision_service.extract_label, image_bytes, content_type)
    while not future.done():
        await asyncio.sleep(0.001)

    return future.result()


@router.post("/verify", response_model=VerificationResult)
async def verify(
    image: UploadFile | None = File(default=None),
    brand_name: str | None = Form(default=None),
    class_type: str | None = Form(default=None),
    abv: str | None = Form(default=None),
    net_contents: str | None = Form(default=None),
    producer: str | None = Form(default=None),
    country_of_origin: str | None = Form(default=None),
    government_warning: str | None = Form(default=None),
    vision_service: VisionServiceDependency = Depends(get_vision_service),
) -> VerificationResult | JSONResponse:
    """Validate a label image and compare extracted fields with application data."""
    started_at = _now_counter()
    status_code = 500
    verdict: str | None = None

    try:
        # Validate required application fields before touching the vision service.
        application_data, field_error = validate_application_fields(
            {
                "brand_name": brand_name,
                "class_type": class_type,
                "abv": abv,
                "net_contents": net_contents,
                "producer": producer,
                "country_of_origin": country_of_origin,
                "government_warning": government_warning,
            }
        )
        if field_error is not None:
            status_code = field_error.status_code
            return field_error

        # Validate upload metadata and bytes before model extraction.
        image_bytes, image_error = await read_validated_image(image)
        if image_error is not None:
            status_code = image_error.status_code
            return image_error

        # Extract visible label fields and run the verification rules.
        resolved_vision_service = resolve_vision_service(vision_service)
        extracted_label = resolved_vision_service.extract_label(
            image_bytes,
            image.content_type if image is not None else None,
        )
        result = verify_label(application_data, extracted_label)

        # Attach endpoint latency to the response without changing result shape.
        endpoint_result = result.model_copy(
            update={"latency_ms": _now_ms_since(started_at)}
        )
        status_code = 200
        verdict = endpoint_result.overall_verdict
        return endpoint_result
    except VisionImageValidationError:
        status_code = 400
        return error_response(
            400,
            "invalid_image",
            "The uploaded file is not a readable image.",
            [{"field": "image", "message": "Upload a readable image file."}],
        )
    except VisionConfigurationError:
        status_code = 500
        return error_response(
            500,
            "vision_not_configured",
            "Vision service is not configured.",
        )
    except VisionAPIError:
        status_code = 502
        return error_response(
            502,
            "vision_extraction_failed",
            "Vision extraction failed. Please try again.",
        )
    except VisionParseError:
        status_code = 502
        return error_response(
            502,
            "vision_result_unreadable",
            "Vision extraction returned an unreadable result.",
        )
    except Exception:
        status_code = 500
        LOGGER.exception("Unexpected /verify endpoint failure")
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred while verifying the label.",
        )
    finally:
        # Record timing and outcome for latency budget monitoring.
        latency_ms = _now_ms_since(started_at)
        LOGGER.info(
            "verify_request_complete",
            extra={
                "latency_ms": latency_ms,
                "over_budget": latency_ms > LATENCY_BUDGET_MS,
                "latency_budget_ms": LATENCY_BUDGET_MS,
                "status_code": status_code,
                "overall_verdict": verdict,
            },
        )


@router.post("/verify/batch", response_model=BatchVerificationResponse)
async def verify_batch_endpoint(
    request: Request,
    items: str | None = Form(default=None),
    vision_service: VisionServiceDependency = Depends(get_vision_service),
) -> BatchVerificationResponse | JSONResponse:
    """Validate and verify multiple label images concurrently."""
    started_at = _now_counter()
    status_code = 500
    completed = 0
    failed = 0

    try:
        batch_items, batch_error = _parse_batch_items(items)
        if batch_error is not None:
            status_code = batch_error.status_code
            return batch_error
        assert batch_items is not None

        form = await request.form()
        uploads: dict[str, UploadFile] = {}
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
            status_code = 422
            return error_response(
                422,
                "missing_upload_fields",
                "One or more batch image uploads are missing.",
                missing_uploads,
            )

        resolved_vision_service = resolve_vision_service(vision_service)
        max_concurrency = _max_batch_concurrency()
        semaphore = asyncio.Semaphore(max_concurrency)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency)
        try:
            results = await asyncio.gather(
                *[
                    _verify_batch_item(
                        item=item,
                        upload=uploads[item["image_field"]],
                        vision_service=resolved_vision_service,
                        semaphore=semaphore,
                        executor=executor,
                    )
                    for item in batch_items
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
        needs_review = sum(
            item.status == "completed"
            and item.result is not None
            and item.result.overall_verdict == "NEEDS_REVIEW"
            for item in results
        )
        completed = passed + needs_review
        failed = sum(item.status == "failed" for item in results)
        status_code = 200
        return BatchVerificationResponse(
            items=results,
            summary=BatchVerificationSummary(
                passed=passed,
                needs_review=needs_review,
                completed=completed,
                failed=failed,
                total=len(results),
            ),
            latency_ms=_now_ms_since(started_at),
        )
    except Exception:
        status_code = 500
        LOGGER.exception("Unexpected /verify/batch endpoint failure")
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred while verifying the batch.",
        )
    finally:
        latency_ms = _now_ms_since(started_at)
        LOGGER.info(
            "verify_batch_request_complete",
            extra={
                "latency_ms": latency_ms,
                "over_budget": latency_ms > LATENCY_BUDGET_MS,
                "latency_budget_ms": LATENCY_BUDGET_MS,
                "status_code": status_code,
                "item_count": completed + failed,
                "completed_count": completed,
                "failed_count": failed,
            },
        )
