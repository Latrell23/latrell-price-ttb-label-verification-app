from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.errors import vision_exception_response
from app.responses import error_response
from app.review import (
    ReviewLabelList,
    get_review_label,
    list_review_labels,
    verify_review_label,
    verify_review_queue,
)
from app.verification import ReviewVerificationItem, ReviewVerificationResponse
from app.vision.dependencies import (
    get_vision_service,
    resolve_vision_service,
)


router = APIRouter(prefix="/review")


@router.get("/labels", response_model=ReviewLabelList)
async def review_labels() -> ReviewLabelList:
    """Return simulated backend-owned labels ready for reviewer verification."""
    return ReviewLabelList(
        items=[label.to_public() for label in list_review_labels()],
    )


@router.post("/labels/{label_id}/verify", response_model=ReviewVerificationItem)
async def verify_review_label_endpoint(
    label_id: str,
) -> ReviewVerificationItem | JSONResponse:
    """Verify one simulated review label against its backend JSON."""
    label = get_review_label(label_id)
    if label is None:
        return error_response(
            404,
            "review_label_not_found",
            "The requested review label was not found.",
            [{"field": "label_id", "message": f"Unknown label: {label_id}."}],
        )

    vision_service, vision_error = _review_vision_service()
    if vision_error is not None:
        return vision_error

    return await verify_review_label(
        label=label,
        vision_service=vision_service,
    )


@router.post("/verify", response_model=ReviewVerificationResponse)
async def verify_review_queue_endpoint() -> ReviewVerificationResponse | JSONResponse:
    """Verify every simulated review label in the backend queue."""
    vision_service, vision_error = _review_vision_service()
    if vision_error is not None:
        return vision_error

    return await verify_review_queue(
        labels=list_review_labels(),
        vision_service=vision_service,
    )


def _review_vision_service():
    """Resolve the production vision service inside route error handling."""
    try:
        return resolve_vision_service(get_vision_service()), None
    except Exception as exception:
        response = vision_exception_response(exception)
        if response is not None:
            return None, response
        raise
