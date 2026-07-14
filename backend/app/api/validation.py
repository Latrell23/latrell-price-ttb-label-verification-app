from fastapi import UploadFile
from fastapi.responses import JSONResponse

from app.responses import error_response
from app.verification import ApplicationData


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_TYPE_PREFIX = "image/"


def validate_application_fields(
    form_values: dict[str, str | None],
) -> tuple[ApplicationData | None, JSONResponse | None]:
    """Validate required form fields and return application data or an error."""
    # Report missing fields before trimming present values.
    missing = [
        {"field": field, "message": "This field is required."}
        for field, value in form_values.items()
        if value is None
    ]
    if missing:
        return None, error_response(
            422,
            "missing_required_fields",
            "One or more required application fields are missing.",
            missing,
        )

    # Normalize whitespace and reject fields that become empty.
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
        return None, error_response(
            422,
            "blank_required_fields",
            "One or more required application fields are blank.",
            blank,
        )

    return ApplicationData(**stripped), None


async def read_validated_image(
    image: UploadFile | None,
) -> tuple[bytes | None, JSONResponse | None]:
    """Validate the uploaded image field and return its bytes or an error."""
    # Require an upload before checking media type or size.
    if image is None:
        return None, error_response(
            422,
            "missing_image",
            "The image file field is required.",
            [{"field": "image", "message": "Upload one label image."}],
        )

    # Reject unsupported media types before reading the file body.
    if not (image.content_type or "").startswith(SUPPORTED_IMAGE_TYPE_PREFIX):
        return None, error_response(
            415,
            "unsupported_media_type",
            "The uploaded file must be an image.",
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

    # Read one byte past the limit so oversized uploads can be detected.
    image_bytes = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return None, error_response(
            413,
            "file_too_large",
            "The uploaded image must be 10 MiB or smaller.",
            [{"field": "image", "message": "Maximum size is 10 MiB."}],
        )

    if not image_bytes:
        return None, error_response(
            400,
            "empty_file",
            "The uploaded image file is empty.",
            [{"field": "image", "message": "Upload a non-empty image file."}],
        )

    return image_bytes, None
