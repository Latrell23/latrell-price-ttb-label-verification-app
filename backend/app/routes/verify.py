from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.verify_controller import (
    verify_batch_request,
    verify_batch_stream_request,
    verify_label_request,
)
from app.verification import (
    BatchVerificationResponse,
    VerificationResult,
)
from app.vision.dependencies import (
    VisionServiceDependency,
    get_vision_service,
)


router = APIRouter()


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
    return await verify_label_request(
        image=image,
        application_fields={
            "brand_name": brand_name,
            "class_type": class_type,
            "abv": abv,
            "net_contents": net_contents,
            "producer": producer,
            "country_of_origin": country_of_origin,
            "government_warning": government_warning,
        },
        vision_service=vision_service,
    )


@router.post("/verify/batch", response_model=BatchVerificationResponse)
async def verify_batch_endpoint(
    request: Request,
    items: str | None = Form(default=None),
    vision_service: VisionServiceDependency = Depends(get_vision_service),
) -> BatchVerificationResponse | JSONResponse:
    """Validate and verify multiple label images concurrently."""
    return await verify_batch_request(
        request=request,
        items=items,
        vision_service=vision_service,
    )


@router.post("/verify/batch/stream", response_model=None)
async def verify_batch_stream_endpoint(
    request: Request,
    items: str | None = Form(default=None),
    vision_service: VisionServiceDependency = Depends(get_vision_service),
):
    """Stream batch verification item results as each concurrent item finishes."""
    return await verify_batch_stream_request(
        request=request,
        items=items,
        vision_service=vision_service,
    )
