import logging

from fastapi.responses import JSONResponse

from app.responses import error_response
from app.verification import APIError
from app.vision import (
    VisionAPIError,
    VisionConfigurationError,
    VisionImageValidationError,
    VisionParseError,
)


LOGGER = logging.getLogger("app.main")


def _log_vision_failure(exception: Exception, context: str) -> None:
    reason = (
        exception.reason
        if isinstance(exception, VisionAPIError)
        else "parse_failure"
    )
    LOGGER.warning(
        "vision_request_failed",
        extra={
            "context": context,
            "failure_reason": reason,
            "exception_type": exception.__class__.__name__,
        },
    )


def error_payload(
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> APIError:
    """Build the inner API error shape used by failed review items."""
    return APIError(code=code, message=message, details=details or [])


def vision_exception_error(exception: Exception) -> APIError:
    """Map vision exceptions to reviewer-facing item errors."""
    if isinstance(exception, VisionImageValidationError):
        return error_payload(
            "invalid_image",
            "The label image is not readable.",
            [{"field": "image", "message": "The review image could not be read."}],
        )
    if isinstance(exception, VisionConfigurationError):
        return error_payload(
            "vision_not_configured",
            "Vision service is not configured.",
        )
    if isinstance(exception, VisionAPIError):
        _log_vision_failure(exception, "review_item")
        return error_payload(
            "vision_extraction_failed",
            "Vision extraction failed. Please try again.",
        )
    if isinstance(exception, VisionParseError):
        _log_vision_failure(exception, "review_item")
        return error_payload(
            "vision_result_unreadable",
            "Vision extraction returned an unreadable result.",
        )

    LOGGER.exception("Unexpected review item failure")
    return error_payload(
        "internal_error",
        "An unexpected error occurred while verifying the label.",
    )


def vision_exception_response(exception: Exception) -> JSONResponse | None:
    """Map expected vision setup exceptions to review endpoint responses."""
    if isinstance(exception, VisionImageValidationError):
        return error_response(
            400,
            "invalid_image",
            "The label image is not readable.",
            [{"field": "image", "message": "The review image could not be read."}],
        )
    if isinstance(exception, VisionConfigurationError):
        return error_response(
            500,
            "vision_not_configured",
            "Vision service is not configured.",
        )
    if isinstance(exception, VisionAPIError):
        _log_vision_failure(exception, "review")
        return error_response(
            502,
            "vision_extraction_failed",
            "Vision extraction failed. Please try again.",
        )
    if isinstance(exception, VisionParseError):
        _log_vision_failure(exception, "review")
        return error_response(
            502,
            "vision_result_unreadable",
            "Vision extraction returned an unreadable result.",
        )

    return None
