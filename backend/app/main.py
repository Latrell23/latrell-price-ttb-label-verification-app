import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter

from fastapi import Depends, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.verification import ApplicationData, VerificationResult, verify_label
from app.vision import (
    OpenAIVisionService,
    VisionAPIError,
    VisionConfigurationError,
    VisionImageValidationError,
    VisionParseError,
    VisionService,
)


LOGGER = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
LATENCY_BUDGET_MS = 5000.0
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
VisionServiceDependency = VisionService | Callable[[], VisionService]


def _split_env_list(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def get_vision_service() -> Callable[[], VisionService]:
    return OpenAIVisionService


def _resolve_vision_service(
    vision_service: VisionServiceDependency,
) -> VisionService:
    if isinstance(vision_service, type):
        return vision_service()
    if hasattr(vision_service, "extract_label"):
        return vision_service
    return vision_service()


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
    )


def _validate_application_fields(
    form_values: dict[str, str | None],
) -> tuple[ApplicationData | None, JSONResponse | None]:
    missing = [
        {"field": field, "message": "This field is required."}
        for field, value in form_values.items()
        if value is None
    ]
    if missing:
        return None, _error_response(
            422,
            "missing_required_fields",
            "One or more required application fields are missing.",
            missing,
        )

    stripped = {
        field: value.strip()
        for field, value in form_values.items()
        if value is not None
    }
    blank = [
        {"field": field, "message": "This field cannot be blank."}
        for field, value in stripped.items()
        if value == ""
    ]
    if blank:
        return None, _error_response(
            422,
            "blank_required_fields",
            "One or more required application fields are blank.",
            blank,
        )

    return ApplicationData(**stripped), None


async def _read_validated_image(
    image: UploadFile | None,
) -> tuple[bytes | None, JSONResponse | None]:
    if image is None:
        return None, _error_response(
            422,
            "missing_image",
            "The image file field is required.",
            [{"field": "image", "message": "Upload one label image."}],
        )

    if image.content_type not in SUPPORTED_IMAGE_TYPES:
        return None, _error_response(
            415,
            "unsupported_media_type",
            "The uploaded file must be a JPEG, PNG, or WebP image.",
            [
                {
                    "field": "image",
                    "message": (
                        "Received content type: "
                        f"{image.content_type or 'unknown'}."
                    ),
                }
            ],
        )

    image_bytes = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return None, _error_response(
            413,
            "file_too_large",
            "The uploaded image must be 10 MiB or smaller.",
            [{"field": "image", "message": "Maximum size is 10 MiB."}],
        )
    if not image_bytes:
        return None, _error_response(
            400,
            "empty_file",
            "The uploaded image file is empty.",
            [{"field": "image", "message": "Upload a non-empty image file."}],
        )

    return image_bytes, None


def create_app() -> FastAPI:
    app = FastAPI(title="TTB Label Verification API")

    allowed_origins = _split_env_list(
        os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "ttb-label-verification-api",
            "environment": os.getenv("APP_ENV", "local"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/verify", response_model=VerificationResult)
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
        started_at = perf_counter()
        status_code = 500
        verdict: str | None = None

        try:
            application_data, field_error = _validate_application_fields(
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

            image_bytes, image_error = await _read_validated_image(image)
            if image_error is not None:
                status_code = image_error.status_code
                return image_error

            resolved_vision_service = _resolve_vision_service(vision_service)
            extracted_label = resolved_vision_service.extract_label(
                image_bytes,
                image.content_type if image is not None else None,
            )
            result = verify_label(application_data, extracted_label)
            endpoint_latency_ms = (perf_counter() - started_at) * 1000
            endpoint_result = result.model_copy(
                update={"latency_ms": endpoint_latency_ms}
            )
            status_code = 200
            verdict = endpoint_result.overall_verdict
            return endpoint_result
        except VisionImageValidationError:
            status_code = 400
            return _error_response(
                400,
                "invalid_image",
                "The uploaded file is not a readable image.",
                [{"field": "image", "message": "Upload a readable image file."}],
            )
        except VisionConfigurationError:
            status_code = 500
            return _error_response(
                500,
                "vision_not_configured",
                "Vision service is not configured.",
            )
        except VisionAPIError:
            status_code = 502
            return _error_response(
                502,
                "vision_extraction_failed",
                "Vision extraction failed. Please try again.",
            )
        except VisionParseError:
            status_code = 502
            return _error_response(
                502,
                "vision_result_unreadable",
                "Vision extraction returned an unreadable result.",
            )
        except Exception:
            status_code = 500
            LOGGER.exception("Unexpected /verify endpoint failure")
            return _error_response(
                500,
                "internal_error",
                "An unexpected error occurred while verifying the label.",
            )
        finally:
            latency_ms = (perf_counter() - started_at) * 1000
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

    return app


app = create_app()
