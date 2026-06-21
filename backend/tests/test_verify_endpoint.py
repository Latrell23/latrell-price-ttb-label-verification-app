import asyncio
import json
import logging
from collections.abc import Callable
from io import BytesIO

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, UploadFile

from app.main import create_app
from app.verification.models import ExtractedLabel, VerificationResult
from app.vision import (
    VisionAPIError,
    VisionConfigurationError,
    VisionImageValidationError,
    VisionParseError,
)


WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)

APPLICATION_DATA = {
    "brand_name": "Acme Estate",
    "class_type": "Red Wine",
    "abv": "13.5%",
    "net_contents": "750 mL",
    "producer": "Acme Cellars",
    "country_of_origin": "United States",
    "government_warning": WARNING,
}

IMAGE_BYTES = b"mock image bytes"
DEFAULT_IMAGE = object()


class SpyVisionService:
    def __init__(
        self,
        label: ExtractedLabel | None = None,
        exception_factory: Callable[[], Exception] | None = None,
    ) -> None:
        self.label = label or extracted_label()
        self.exception_factory = exception_factory
        self.calls: list[tuple[bytes, str | None]] = []

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        self.calls.append((image_bytes, content_type))
        if self.exception_factory is not None:
            raise self.exception_factory()
        return self.label


def extracted_label(**overrides: str | None) -> ExtractedLabel:
    data = {
        "brand_name": "Acme Estate",
        "class_type": "Red Wine",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "producer": "Acme Cellars",
        "country_of_origin": "United States",
        "government_warning": WARNING,
        "raw_text": "ACME ESTATE RED WINE ALC. 13.5% BY VOL. 750 mL",
        "extraction_confidence": 0.98,
    }
    data.update(overrides)
    return ExtractedLabel(**data)


def verify_endpoint() -> Callable:
    app = create_app()
    return next(route.endpoint for route in app.routes if route.path == "/verify")


def upload_file(
    content: bytes = IMAGE_BYTES,
    content_type: str = "image/jpeg",
) -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename="label.jpg",
        headers=Headers({"content-type": content_type}),
    )


def call_verify(
    service: SpyVisionService | Callable[[], SpyVisionService],
    *,
    data: dict[str, str] | None = None,
    image: UploadFile | None | object = DEFAULT_IMAGE,
) -> VerificationResult | JSONResponse:
    endpoint = verify_endpoint()
    form_data = APPLICATION_DATA if data is None else data
    upload = upload_file() if image is DEFAULT_IMAGE else image
    return asyncio.run(
        endpoint(
            image=upload,
            brand_name=form_data.get("brand_name"),
            class_type=form_data.get("class_type"),
            abv=form_data.get("abv"),
            net_contents=form_data.get("net_contents"),
            producer=form_data.get("producer"),
            country_of_origin=form_data.get("country_of_origin"),
            government_warning=form_data.get("government_warning"),
            vision_service=service,
        )
    )


def response_status_and_body(response) -> tuple[int, dict]:
    if isinstance(response, JSONResponse):
        return response.status_code, json.loads(response.body)
    return 200, response.model_dump()


def assert_shaped_error(response, expected_status: int) -> dict:
    status_code, body = response_status_and_body(response)
    assert status_code == expected_status
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]
    return body


def assert_no_internal_details(response) -> None:
    _, body = response_status_and_body(response)
    body_text = json.dumps(body)
    forbidden = ("Traceback", "RuntimeError", "ValueError", ".py", "/app/", "boom")
    assert not any(term in body_text for term in forbidden)


def result_for_field(body: dict, field: str) -> dict:
    return next(result for result in body["results"] if result["field"] == field)


def test_verify_success_returns_full_verification_result_and_calls_mock() -> None:
    service = SpyVisionService()

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert set(body) == {"results", "overall_verdict", "latency_ms"}
    assert body["overall_verdict"] == "APPROVED"
    assert body["latency_ms"] > 0
    assert len(body["results"]) == 7
    assert service.calls == [(IMAGE_BYTES, "image/jpeg")]
    for result in body["results"]:
        assert "expected" in result
        assert "found" in result
    warning = result_for_field(body, "government_warning")
    assert warning["expected"] == WARNING
    assert warning["found"] == WARNING


def test_verify_mismatched_extracted_field_returns_needs_review() -> None:
    service = SpyVisionService(extracted_label(brand_name="Wrong Brand"))

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert body["overall_verdict"] == "NEEDS_REVIEW"
    brand = result_for_field(body, "brand_name")
    assert brand["expected"] == "Acme Estate"
    assert brand["found"] == "Wrong Brand"
    assert brand["status"] == "FAIL"


def test_verify_warning_failure_surfaces_extracted_warning_text() -> None:
    misread_warning = WARNING.replace("SURGEON", "S URGE0N", 1)
    service = SpyVisionService(extracted_label(government_warning=misread_warning))

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    warning = result_for_field(body, "government_warning")
    assert warning["status"] == "FAIL"
    assert warning["expected"] == WARNING
    assert warning["found"] == misread_warning


def test_verify_missing_image_returns_readable_422_error() -> None:
    service = SpyVisionService()

    response = call_verify(service, image=None)

    body = assert_shaped_error(response, 422)
    assert body["error"]["code"] == "missing_image"
    assert "image" in body["error"]["message"].lower()
    assert_no_internal_details(response)


def test_verify_missing_required_application_field_returns_422() -> None:
    service = SpyVisionService()
    data = APPLICATION_DATA.copy()
    data.pop("producer")

    response = call_verify(service, data=data)

    body = assert_shaped_error(response, 422)
    assert body["error"]["code"] == "missing_required_fields"
    assert body["error"]["details"] == [
        {"field": "producer", "message": "This field is required."}
    ]
    assert_no_internal_details(response)


def test_verify_blank_required_application_field_returns_422() -> None:
    service = SpyVisionService()
    data = APPLICATION_DATA | {"producer": " \n\t "}

    response = call_verify(service, data=data)

    body = assert_shaped_error(response, 422)
    assert body["error"]["code"] == "blank_required_fields"
    assert body["error"]["details"] == [
        {"field": "producer", "message": "This field cannot be blank."}
    ]
    assert_no_internal_details(response)


def test_verify_unsupported_content_type_returns_415() -> None:
    service = SpyVisionService()

    response = call_verify(
        service,
        image=upload_file(content=b"%PDF", content_type="application/pdf"),
    )

    body = assert_shaped_error(response, 415)
    assert body["error"]["code"] == "unsupported_media_type"
    assert_no_internal_details(response)


def test_verify_unsupported_content_type_does_not_construct_vision_service() -> None:
    def unavailable_service() -> SpyVisionService:
        raise VisionConfigurationError("missing api key")

    response = call_verify(
        unavailable_service,
        image=upload_file(content=b"%PDF", content_type="application/pdf"),
    )

    body = assert_shaped_error(response, 415)
    assert body["error"]["code"] == "unsupported_media_type"
    assert_no_internal_details(response)


def test_verify_empty_image_file_returns_400() -> None:
    service = SpyVisionService()

    response = call_verify(service, image=upload_file(content=b""))

    body = assert_shaped_error(response, 400)
    assert body["error"]["code"] == "empty_file"
    assert_no_internal_details(response)


def test_verify_file_over_ten_mib_returns_413() -> None:
    service = SpyVisionService()

    response = call_verify(
        service,
        image=upload_file(content=b"x" * (10 * 1024 * 1024 + 1)),
    )

    body = assert_shaped_error(response, 413)
    assert body["error"]["code"] == "file_too_large"
    assert_no_internal_details(response)


def test_verify_vision_image_validation_error_returns_400() -> None:
    service = SpyVisionService(
        exception_factory=lambda: VisionImageValidationError("bad bytes")
    )

    response = call_verify(service)

    body = assert_shaped_error(response, 400)
    assert body["error"]["code"] == "invalid_image"
    assert_no_internal_details(response)


def test_verify_vision_configuration_error_returns_500() -> None:
    def unavailable_service() -> SpyVisionService:
        raise VisionConfigurationError("missing api key")

    response = call_verify(unavailable_service)

    body = assert_shaped_error(response, 500)
    assert body["error"]["code"] == "vision_not_configured"
    assert_no_internal_details(response)


def test_verify_vision_api_error_returns_502() -> None:
    service = SpyVisionService(exception_factory=lambda: VisionAPIError("sdk says no"))

    response = call_verify(service)

    body = assert_shaped_error(response, 502)
    assert body["error"]["code"] == "vision_extraction_failed"
    assert_no_internal_details(response)


def test_verify_vision_parse_error_returns_502() -> None:
    service = SpyVisionService(exception_factory=lambda: VisionParseError("bad json"))

    response = call_verify(service)

    body = assert_shaped_error(response, 502)
    assert body["error"]["code"] == "vision_result_unreadable"
    assert_no_internal_details(response)


def test_verify_unexpected_error_returns_generic_500_without_internals() -> None:
    service = SpyVisionService(exception_factory=lambda: RuntimeError("boom"))

    response = call_verify(service)

    body = assert_shaped_error(response, 500)
    assert body["error"]["code"] == "internal_error"
    assert_no_internal_details(response)


def test_verify_logs_latency_and_five_second_budget(monkeypatch, caplog) -> None:
    service = SpyVisionService()
    times = iter([100.0, 106.25, 106.26])

    monkeypatch.setattr("app.main.perf_counter", lambda: next(times))
    caplog.set_level(logging.INFO, logger="app.main")

    response = call_verify(service)

    status_code, _ = response_status_and_body(response)
    assert status_code == 200
    record = next(
        record for record in caplog.records if record.message == "verify_request_complete"
    )
    assert record.latency_ms > 5000
    assert record.over_budget is True
    assert record.latency_budget_ms == 5000.0
    assert record.status_code == 200
    assert record.overall_verdict == "APPROVED"
