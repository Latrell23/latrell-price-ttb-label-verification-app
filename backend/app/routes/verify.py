import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.responses import error_response
from app.routes.validation import read_validated_image, validate_application_fields
from app.verification import VerificationResult, verify_label
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
VisionServiceDependency = VisionService | Callable[[], VisionService]

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
