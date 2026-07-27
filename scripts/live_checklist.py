#!/usr/bin/env python3
import argparse
import os
import sys
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://latrell-price-ttb-label-verification-app.onrender.com"


class SmokeFailure(AssertionError):
    """Raised when the deployed review API does not match its public contract."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deployed health and review-queue smoke checks."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LIVE_BASE_URL") or DEFAULT_BASE_URL,
        help="Backend base URL. Defaults to LIVE_BASE_URL or the Render service.",
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
            timeout_seconds=args.timeout,
        )
    except (SmokeFailure, httpx.HTTPError) as exc:
        print(f"live smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"live smoke passed: {args.base_url.rstrip('/')}")
    return 0


def run_live_checklist(*, base_url: str, timeout_seconds: float) -> None:
    base_url = base_url.rstrip("/")

    with httpx.Client(timeout=timeout_seconds) as client:
        health = _request_json(client, "GET", f"{base_url}/health")
        if health.get("status") != "healthy":
            raise SmokeFailure("GET /health did not report healthy")

        queue = _request_json(client, "GET", f"{base_url}/review/labels")
        items = queue.get("items")
        if not isinstance(items, list) or not items:
            raise SmokeFailure("GET /review/labels returned an empty or invalid queue")

        first_id = items[0].get("id")
        if not isinstance(first_id, str) or not first_id:
            raise SmokeFailure("GET /review/labels returned an item without an id")

        single = _request_json(
            client,
            "POST",
            f"{base_url}/review/labels/{first_id}/verify",
        )
        _assert_review_item(single, first_id)

        full_queue = _request_json(
            client,
            "POST",
            f"{base_url}/review/verify",
        )
        _assert_review_queue(full_queue, expected_total=len(items))


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
) -> dict[str, Any]:
    response = client.request(method, url, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise SmokeFailure(f"{method} {url} returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SmokeFailure(f"{method} {url} returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{method} {url} returned an invalid JSON shape")
    return payload


def _assert_review_item(item: dict[str, Any], expected_id: str) -> None:
    if item.get("client_id") != expected_id:
        raise SmokeFailure("Single-label review returned the wrong label id")
    if item.get("status") not in {"completed", "failed"}:
        raise SmokeFailure("Single-label review returned an invalid status")
    if item.get("status") == "completed" and not isinstance(item.get("result"), dict):
        raise SmokeFailure("Completed single-label review is missing its result")


def _assert_review_queue(payload: dict[str, Any], expected_total: int) -> None:
    items = payload.get("items")
    summary = payload.get("summary")
    if not isinstance(items, list) or len(items) != expected_total:
        raise SmokeFailure("Full-queue review returned the wrong item count")
    if not isinstance(summary, dict) or summary.get("total") != expected_total:
        raise SmokeFailure("Full-queue review returned an invalid summary")
    if summary.get("completed", 0) + summary.get("failed", 0) != expected_total:
        raise SmokeFailure("Full-queue review summary counts do not balance")


if __name__ == "__main__":
    raise SystemExit(main())
