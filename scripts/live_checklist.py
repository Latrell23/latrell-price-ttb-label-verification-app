#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://latrell-price-ttb-label-verification-app.onrender.com"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_label.jpg"

GOVERNMENT_WARNING = (
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
    "government_warning": GOVERNMENT_WARNING,
}


class SmokeFailure(AssertionError):
    """Raised when the deployed smoke check fails with an actionable reason."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deployed end-to-end health, single, and batch smoke checks."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LIVE_BASE_URL") or DEFAULT_BASE_URL,
        help="Deployed backend base URL. Defaults to LIVE_BASE_URL or Render.",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_IMAGE_PATH,
        help="JPEG sample label image to post to /verify.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("LIVE_TIMEOUT_SECONDS", "90")),
        help="HTTP timeout in seconds for each deployed request.",
    )
    args = parser.parse_args()

    try:
        run_live_checklist(
            base_url=args.base_url,
            image_path=args.image,
            timeout_seconds=args.timeout,
        )
    except (SmokeFailure, httpx.HTTPError) as exc:
        print(f"live smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"live smoke passed: {args.base_url.rstrip('/')}")
    return 0


def run_live_checklist(
    *,
    base_url: str,
    image_path: Path,
    timeout_seconds: float,
) -> None:
    base_url = base_url.rstrip("/")
    if not image_path.exists():
        raise SmokeFailure(f"fixture image not found: {image_path}")

    image_bytes = image_path.read_bytes()
    if len(image_bytes) > 200 * 1024:
        raise SmokeFailure(f"fixture image exceeds 200 KB: {len(image_bytes)} bytes")

    with httpx.Client(timeout=timeout_seconds) as client:
        health = _request_json(client, "GET /health", "GET", f"{base_url}/health")
        _assert_health(health)

        single = _request_json(
            client,
            "POST /verify",
            "POST",
            f"{base_url}/verify",
            data=APPLICATION_DATA,
            files={"image": (image_path.name, image_bytes, "image/jpeg")},
            headers={"Accept": "application/json"},
        )
        _assert_verification_result(single, "POST /verify")

        batch_items = [
            {
                "client_id": f"sample-{index}",
                "image_field": f"image_{index}",
                **APPLICATION_DATA,
            }
            for index in range(2)
        ]
        batch = _request_json(
            client,
            "POST /verify/batch",
            "POST",
            f"{base_url}/verify/batch",
            data={"items": json.dumps(batch_items)},
            files=[
                (f"image_{index}", (image_path.name, image_bytes, "image/jpeg"))
                for index in range(2)
            ],
            headers={"Accept": "application/json"},
        )
        _assert_batch_result(batch)


def _request_json(
    client: httpx.Client,
    label: str,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise SmokeFailure(f"{label} timed out") from exc
    except httpx.HTTPError as exc:
        raise SmokeFailure(f"{label} request failed: {exc}") from exc
    return _json_response(response, label)


def _json_response(response: httpx.Response, label: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise SmokeFailure(f"{label} returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{label} returned non-JSON body") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{label} returned non-object JSON")
    return payload


def _assert_health(payload: dict[str, Any]) -> None:
    if payload.get("status") != "healthy":
        raise SmokeFailure("GET /health did not report status=healthy")
    if payload.get("vision_configured") is not True:
        raise SmokeFailure("GET /health did not report vision_configured=true")


def _assert_verification_result(payload: dict[str, Any], label: str) -> None:
    if set(payload) != {"results", "overall_verdict", "latency_ms"}:
        raise SmokeFailure(f"{label} returned unexpected VerificationResult keys")
    if payload["overall_verdict"] not in {"APPROVED", "NEEDS_REVIEW"}:
        raise SmokeFailure(f"{label} returned invalid overall_verdict")
    if not isinstance(payload["latency_ms"], (int, float)):
        raise SmokeFailure(f"{label} returned missing latency_ms")
    if not isinstance(payload["results"], list) or not payload["results"]:
        raise SmokeFailure(f"{label} returned empty results")

    required_result_keys = {"field", "match_type", "expected", "found", "status"}
    for index, result in enumerate(payload["results"]):
        if not isinstance(result, dict) or set(result) != required_result_keys:
            raise SmokeFailure(f"{label} result {index} has invalid field shape")
        if result["status"] not in {"PASS", "FAIL"}:
            raise SmokeFailure(f"{label} result {index} has invalid status")


def _assert_batch_result(payload: dict[str, Any]) -> None:
    if set(payload) != {"items", "summary", "latency_ms"}:
        raise SmokeFailure("POST /verify/batch returned unexpected response keys")
    if not isinstance(payload["latency_ms"], (int, float)):
        raise SmokeFailure("POST /verify/batch returned missing latency_ms")

    summary = payload["summary"]
    if not isinstance(summary, dict):
        raise SmokeFailure("POST /verify/batch returned invalid summary")
    if summary.get("passed", 0) + summary.get("needs_review", 0) != 2:
        raise SmokeFailure("POST /verify/batch did not complete two labels")

    items = payload["items"]
    if not isinstance(items, list) or len(items) != 2:
        raise SmokeFailure("POST /verify/batch returned invalid item count")
    for index, item in enumerate(items):
        if item.get("status") != "completed":
            raise SmokeFailure(f"POST /verify/batch item {index} did not complete")
        result = item.get("result")
        if not isinstance(result, dict):
            raise SmokeFailure(f"POST /verify/batch item {index} missing result")
        _assert_verification_result(result, f"POST /verify/batch item {index}")


if __name__ == "__main__":
    raise SystemExit(main())
