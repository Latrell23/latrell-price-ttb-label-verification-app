import asyncio
import json
import time

from fastapi.responses import JSONResponse

from app.routes.review import (
    review_labels,
    verify_review_label_endpoint,
    verify_review_queue_endpoint,
)
from app.verification import ExtractedLabel


WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)


class ReviewVisionService:
    def __init__(self, label: ExtractedLabel | None = None) -> None:
        self.label = label or ExtractedLabel(
            brand_name="Acme Estate",
            class_type="Red Wine",
            abv="13.5%",
            net_contents="750 mL",
            producer="Acme Cellars",
            country_of_origin="United States",
            government_warning=WARNING,
            raw_text="ACME ESTATE RED WINE ALC. 13.5% BY VOL. 750 mL",
            extraction_confidence=0.98,
        )
        self.calls: list[tuple[bytes, str | None]] = []
        self.deadlines: list[float | None] = []

    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
        *,
        deadline: float | None = None,
    ) -> ExtractedLabel:
        self.calls.append((image_bytes, content_type))
        self.deadlines.append(deadline)
        return self.label


def response_status_and_body(response) -> tuple[int, dict]:
    if isinstance(response, JSONResponse):
        return response.status_code, json.loads(response.body)
    return 200, response.model_dump()


def test_review_labels_returns_backend_owned_queue() -> None:
    body = asyncio.run(review_labels()).model_dump()

    assert len(body["items"]) == 5
    assert set(body["items"][0]) == {"id", "title", "image_url", "expected"}
    assert body["items"][0]["image_url"].startswith("/review/assets/")
    assert body["items"][0]["expected"]["brand_name"] == "Acme Estate"


def test_verify_review_label_returns_not_found_for_unknown_id() -> None:
    response = asyncio.run(verify_review_label_endpoint("missing-label"))

    status_code, body = response_status_and_body(response)

    assert status_code == 404
    assert body["error"]["code"] == "review_label_not_found"


def test_verify_review_label_uses_fixture_image_and_expected_json(monkeypatch) -> None:
    service = ReviewVisionService()
    monkeypatch.setattr("app.routes.review.get_vision_service", lambda: service)
    response = asyncio.run(verify_review_label_endpoint("label-001"))

    status_code, body = response_status_and_body(response)

    assert status_code == 200
    assert body["client_id"] == "label-001"
    assert body["file_name"] == "label-001.jpg"
    assert body["status"] == "completed"
    assert body["result"]["overall_verdict"] == "APPROVED"
    assert service.calls[0][1] == "image/jpeg"
    assert service.calls[0][0].startswith(b"\xff\xd8")


def test_verify_review_label_uses_review_timeout_budget(monkeypatch) -> None:
    service = ReviewVisionService()
    monkeypatch.setenv("REVIEW_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr("app.routes.review.get_vision_service", lambda: service)

    asyncio.run(verify_review_label_endpoint("label-001"))

    assert service.deadlines[0] is not None
    assert service.deadlines[0] - time.monotonic() > 10


def test_verify_review_queue_returns_batch_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.review.get_vision_service",
        lambda: ReviewVisionService(),
    )
    response = asyncio.run(verify_review_queue_endpoint())
    body = response.model_dump()

    assert len(body["items"]) == 5
    assert body["summary"]["total"] == 5
    assert body["summary"]["completed"] == 5
    assert body["summary"]["failed"] == 0
