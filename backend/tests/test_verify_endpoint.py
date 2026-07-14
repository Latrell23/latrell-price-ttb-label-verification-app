import asyncio
import json
import logging
import time
from collections.abc import Callable
from io import BytesIO
from threading import Lock
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, UploadFile

from app.main import create_app
from app.routes.verify import verify_batch_endpoint, verify_batch_stream_endpoint
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


class SequenceVisionService:
    def __init__(
        self,
        labels: list[ExtractedLabel] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.labels = labels or [extracted_label()]
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[bytes, str | None]] = []
        self._lock = Lock()

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        with self._lock:
            self.calls.append((image_bytes, content_type))
            index = len(self.calls) - 1

        return self.labels[min(index, len(self.labels) - 1)]


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
    filename: str = "label.jpg",
) -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename=filename,
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


def batch_items(count: int, **overrides: str) -> list[dict[str, str]]:
    return [
        {
            "client_id": f"label-{index}",
            "image_field": f"image_{index}",
            **APPLICATION_DATA,
            **overrides,
        }
        for index in range(count)
    ]


class FakeBatchRequest:
    def __init__(self, form_data: dict[str, UploadFile]) -> None:
        self.form_data = form_data

    async def form(self) -> dict[str, UploadFile]:
        return self.form_data


def batch_files(count: int, content_type: str = "image/jpeg") -> dict[str, UploadFile]:
    return {
        f"image_{index}": upload_file(
            content=f"image bytes {index}".encode(),
            content_type=content_type,
            filename=f"label-{index}.jpg",
        )
        for index in range(count)
    }


def post_batch(
    service: SequenceVisionService,
    items: list[dict[str, str]] | str | None,
    files: dict[str, UploadFile] | None = None,
):
    item_payload = None if items is None else items if isinstance(items, str) else json.dumps(items)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        verify_batch_endpoint(
            request=FakeBatchRequest(
                files if files is not None else batch_files(len(items) if isinstance(items, list) else 1)
            ),
            items=item_payload,
            vision_service=service,
        )
    )
    status_code, body = response_status_and_body(result)
    return SimpleNamespace(status_code=status_code, json=lambda: body)


def collect_batch_stream(
    service: SequenceVisionService,
    items: list[dict[str, str]],
    files: dict[str, UploadFile] | None = None,
    close_files_before_iterating: bool = False,
) -> list[dict]:
    async def run_stream() -> list[dict]:
        request_files = files if files is not None else batch_files(len(items))
        response = await verify_batch_stream_endpoint(
            request=FakeBatchRequest(request_files),
            items=json.dumps(items),
            vision_service=service,
        )
        if close_files_before_iterating:
            for upload in request_files.values():
                upload.file.close()

        events = []
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            events.extend(json.loads(line) for line in text.splitlines() if line)
        return events

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(run_stream())


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


def test_verify_instantiates_vision_service_class_before_extracting() -> None:
    response = call_verify(SpyVisionService)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert body["overall_verdict"] == "APPROVED"


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


def test_verify_case_only_application_difference_is_approved() -> None:
    service = SpyVisionService(extracted_label(brand_name="ACME ESTATE"))

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert body["overall_verdict"] == "APPROVED"
    assert result_for_field(body, "brand_name")["status"] == "PASS"


def test_verify_imperfect_readable_image_returns_needs_review_with_null_fields() -> None:
    service = SpyVisionService(
        extracted_label(
            class_type=None,
            producer=None,
            government_warning=None,
            extraction_confidence=0.36,
        )
    )

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert body["overall_verdict"] == "NEEDS_REVIEW"
    assert result_for_field(body, "class_type")["found"] is None
    assert result_for_field(body, "government_warning")["status"] == "FAIL"


def test_verify_non_label_image_returns_needs_review_not_hallucinated_values() -> None:
    service = SpyVisionService(
        extracted_label(
            brand_name=None,
            class_type=None,
            abv=None,
            net_contents=None,
            producer=None,
            country_of_origin=None,
            government_warning=None,
            raw_text=None,
            extraction_confidence=0.0,
        )
    )

    response = call_verify(service)

    status_code, body = response_status_and_body(response)
    assert status_code == 200
    assert body["overall_verdict"] == "NEEDS_REVIEW"
    assert all(result["found"] is None for result in body["results"])


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
    assert service.calls == []
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


def test_verify_accepts_image_content_types_matching_picker_allowlist() -> None:
    service = SpyVisionService()

    response = call_verify(
        service,
        image=upload_file(content=IMAGE_BYTES, content_type="image/heic"),
    )

    status_code, _ = response_status_and_body(response)
    assert status_code == 200
    assert service.calls == [(IMAGE_BYTES, "image/heic")]


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


def test_verify_backend_timeout_returns_502(monkeypatch) -> None:
    class SlowVisionService:
        def extract_label(
            self, image_bytes: bytes, content_type: str | None = None
        ) -> ExtractedLabel:
            time.sleep(0.1)
            return extracted_label()

    monkeypatch.setattr("app.vision.extraction.DEFAULT_TIMEOUT_SECONDS", 0.01)

    response = call_verify(SlowVisionService())

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


def test_verify_batch_success_returns_summary_and_item_results() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])

    response = post_batch(service, batch_items(2), batch_files(2))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "summary", "latency_ms"}
    assert body["summary"] == {
        "passed": 2,
        "needs_review": 0,
        "completed": 2,
        "failed": 0,
        "total": 2,
    }
    assert [item["status"] for item in body["items"]] == ["completed", "completed"]
    assert body["items"][0]["client_id"] == "label-0"
    assert body["items"][0]["file_name"] == "label-0.jpg"
    assert body["items"][0]["result"]["overall_verdict"] == "APPROVED"
    assert len(body["items"][0]["result"]["results"]) == 7
    assert body["items"][0]["error"] is None
    assert len(service.calls) == 2


def test_verify_batch_mixed_approved_and_needs_review_counts_correctly() -> None:
    service = SequenceVisionService(
        [extracted_label(), extracted_label(brand_name="Wrong Brand")]
    )

    response = post_batch(service, batch_items(2), batch_files(2))

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "passed": 1,
        "needs_review": 1,
        "completed": 2,
        "failed": 0,
        "total": 2,
    }
    assert body["items"][1]["result"]["overall_verdict"] == "NEEDS_REVIEW"


def test_verify_batch_one_invalid_item_does_not_block_other_items() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])
    items = batch_items(2)
    items[0]["producer"] = " "

    response = post_batch(service, items, batch_files(2))

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "passed": 1,
        "needs_review": 0,
        "completed": 1,
        "failed": 1,
        "total": 2,
    }
    assert body["items"][0]["status"] == "failed"
    assert body["items"][0]["error"]["code"] == "blank_required_fields"
    assert body["items"][1]["status"] == "completed"
    assert body["items"][1]["result"]["overall_verdict"] == "APPROVED"
    assert len(service.calls) == 1


def test_verify_batch_too_many_items_returns_whole_request_422() -> None:
    service = SequenceVisionService()

    response = post_batch(service, batch_items(6), batch_files(6))

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "too_many_items"
    assert service.calls == []


def test_verify_batch_item_cap_uses_env_before_reading_uploads(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BATCH_ITEMS", "2")
    service = SequenceVisionService()

    response = post_batch(service, batch_items(3), batch_files(3))

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "too_many_items"
    assert body["error"]["details"] == [
        {"field": "items", "message": "Maximum is 2 labels."}
    ]
    assert service.calls == []


def test_verify_batch_missing_items_returns_whole_request_422() -> None:
    service = SequenceVisionService()

    response = post_batch(service, None, batch_files(1))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_items"


def test_verify_batch_malformed_json_returns_whole_request_422() -> None:
    service = SequenceVisionService()

    response = post_batch(service, "{not json", batch_files(1))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "malformed_items"


def test_verify_batch_missing_upload_field_returns_whole_request_422() -> None:
    service = SequenceVisionService()

    response = post_batch(service, batch_items(1), files={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_upload_fields"
    assert service.calls == []


def test_verify_batch_duplicate_client_id_returns_whole_request_422() -> None:
    service = SequenceVisionService()
    items = batch_items(2)
    items[1]["client_id"] = items[0]["client_id"]

    response = post_batch(service, items, batch_files(2))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "duplicate_client_id"


def test_verify_batch_duplicate_image_field_returns_whole_request_422() -> None:
    service = SequenceVisionService()
    items = batch_items(2)
    items[1]["image_field"] = items[0]["image_field"]

    response = post_batch(service, items, batch_files(2))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "duplicate_image_field"


def test_verify_batch_unsupported_media_type_is_per_item_error() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])
    files = batch_files(2)
    files["image_0"] = upload_file(
        content=b"%PDF",
        content_type="application/pdf",
        filename="label-0.pdf",
    )

    response = post_batch(service, batch_items(2), files)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["completed"] == 1
    assert body["summary"]["failed"] == 1
    assert body["items"][0]["error"]["code"] == "unsupported_media_type"
    assert body["items"][1]["result"]["overall_verdict"] == "APPROVED"
    assert len(service.calls) == 1


def test_verify_batch_empty_file_is_per_item_error() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])
    files = batch_files(2)
    files["image_0"] = upload_file(content=b"", filename="label-0.jpg")

    response = post_batch(service, batch_items(2), files)

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["error"]["code"] == "empty_file"
    assert body["summary"]["completed"] == 1
    assert body["summary"]["failed"] == 1


def test_verify_batch_oversized_file_is_per_item_error() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])
    files = batch_files(2)
    files["image_0"] = upload_file(
        content=b"x" * (10 * 1024 * 1024 + 1),
        filename="label-0.jpg",
    )

    response = post_batch(service, batch_items(2), files)

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["error"]["code"] == "file_too_large"
    assert body["summary"]["completed"] == 1
    assert body["summary"]["failed"] == 1


def test_verify_batch_processes_three_labels_concurrently(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BATCH_CONCURRENCY", "3")
    service = SequenceVisionService(
        [extracted_label(), extracted_label(), extracted_label()],
        delay_seconds=0.18,
    )

    started_at = time.perf_counter()
    response = post_batch(service, batch_items(3), batch_files(3))
    latency_seconds = time.perf_counter() - started_at

    assert response.status_code == 200
    assert response.json()["summary"]["completed"] == 3
    assert len(service.calls) == 3
    assert latency_seconds < 0.45


def test_verify_batch_stream_reports_real_item_progress(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BATCH_CONCURRENCY", "3")
    service = SequenceVisionService(
        [extracted_label(), extracted_label(), extracted_label()],
        delay_seconds=0.05,
    )

    events = collect_batch_stream(service, batch_items(3), batch_files(3))

    item_events = [event for event in events if event["type"] == "item"]
    complete_event = next(event for event in events if event["type"] == "complete")
    assert [event["progress"] for event in item_events] == [
        {"completed": 1, "total": 3},
        {"completed": 2, "total": 3},
        {"completed": 3, "total": 3},
    ]
    assert [event["item"]["status"] for event in item_events] == [
        "completed",
        "completed",
        "completed",
    ]
    assert complete_event["summary"] == {
        "passed": 3,
        "needs_review": 0,
        "completed": 3,
        "failed": 0,
        "total": 3,
    }


def test_verify_batch_stream_does_not_read_uploads_after_response_starts() -> None:
    service = SequenceVisionService([extracted_label(), extracted_label()])

    events = collect_batch_stream(
        service,
        batch_items(2),
        batch_files(2),
        close_files_before_iterating=True,
    )

    item_events = [event for event in events if event["type"] == "item"]
    complete_event = next(event for event in events if event["type"] == "complete")
    assert [event["item"]["status"] for event in item_events] == [
        "completed",
        "completed",
    ]
    assert complete_event["summary"] == {
        "passed": 2,
        "needs_review": 0,
        "completed": 2,
        "failed": 0,
        "total": 2,
    }
