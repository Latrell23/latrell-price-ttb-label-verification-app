import concurrent.futures
import logging
import time

from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.batch import (
    build_batch_response,
    collect_batch_uploads,
    parse_batch_items,
    prepare_batch_uploads,
    run_batch_verification,
    stream_batch_results,
    summarize_batch_results,
)
from app.api.errors import vision_exception_response
from app.api.timing import (
    log_batch_complete,
    log_verify_complete,
    now_counter,
    now_ms_since,
)
from app.api.validation import read_validated_image, validate_application_fields
from app.responses import error_response
from app.verification import BatchVerificationResponse, VerificationResult, verify_label
from app.vision import DEFAULT_TIMEOUT_SECONDS, extract_label_with_timeout
from app.vision.dependencies import VisionServiceDependency, resolve_vision_service


LOGGER = logging.getLogger("app.main")


async def verify_label_request(
    *,
    image: UploadFile | None,
    application_fields: dict[str, str | None],
    vision_service: VisionServiceDependency,
) -> VerificationResult | JSONResponse:
    """Orchestrate a single label verification request."""
    started_at = now_counter()
    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
    status_code = 500
    verdict: str | None = None

    try:
        application_data, field_error = validate_application_fields(application_fields)
        if field_error is not None:
            status_code = field_error.status_code
            return field_error

        image_bytes, image_error = await read_validated_image(image)
        if image_error is not None:
            status_code = image_error.status_code
            return image_error

        resolved_vision_service = resolve_vision_service(vision_service)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            extracted_label = await extract_label_with_timeout(
                resolved_vision_service,
                image_bytes,
                image.content_type if image is not None else None,
                executor,
                deadline=deadline,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        result = verify_label(application_data, extracted_label)
        endpoint_result = result.model_copy(
            update={"latency_ms": now_ms_since(started_at)}
        )
        status_code = 200
        verdict = endpoint_result.overall_verdict
        return endpoint_result
    except Exception as exception:
        response = vision_exception_response(exception)
        if response is not None:
            status_code = response.status_code
            return response

        status_code = 500
        LOGGER.exception("Unexpected /verify endpoint failure")
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred while verifying the label.",
        )
    finally:
        log_verify_complete(
            started_at=started_at,
            status_code=status_code,
            verdict=verdict,
        )


async def verify_batch_request(
    *,
    request: Request,
    items: str | None,
    vision_service: VisionServiceDependency,
) -> BatchVerificationResponse | JSONResponse:
    """Orchestrate a non-streaming batch verification request."""
    started_at = now_counter()
    status_code = 500
    completed = 0
    failed = 0

    try:
        batch_items, batch_error = parse_batch_items(items)
        if batch_error is not None:
            status_code = batch_error.status_code
            return batch_error
        assert batch_items is not None

        form = await request.form()
        uploads, upload_error = collect_batch_uploads(batch_items, form)
        if upload_error is not None:
            status_code = upload_error.status_code
            return upload_error
        assert uploads is not None

        resolved_vision_service = resolve_vision_service(vision_service)
        results = await run_batch_verification(
            batch_items=batch_items,
            uploads=uploads,
            vision_service=resolved_vision_service,
        )

        _, _, completed, failed = summarize_batch_results(results)
        status_code = 200
        return build_batch_response(results=results, started_at=started_at)
    except Exception:
        status_code = 500
        LOGGER.exception("Unexpected /verify/batch endpoint failure")
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred while verifying the batch.",
        )
    finally:
        log_batch_complete(
            started_at=started_at,
            status_code=status_code,
            completed=completed,
            failed=failed,
        )


async def verify_batch_stream_request(
    *,
    request: Request,
    items: str | None,
    vision_service: VisionServiceDependency,
) -> JSONResponse | StreamingResponse:
    """Orchestrate a streaming batch verification request."""
    started_at = now_counter()

    batch_items, batch_error = parse_batch_items(items)
    if batch_error is not None:
        return batch_error
    assert batch_items is not None

    form = await request.form()
    uploads, upload_error = collect_batch_uploads(batch_items, form)
    if upload_error is not None:
        return upload_error
    assert uploads is not None

    prepared_uploads = await prepare_batch_uploads(batch_items, uploads)
    resolved_vision_service = resolve_vision_service(vision_service)

    return StreamingResponse(
        stream_batch_results(
            batch_items=batch_items,
            prepared_uploads=prepared_uploads,
            vision_service=resolved_vision_service,
            started_at=started_at,
        ),
        media_type="application/x-ndjson",
    )
