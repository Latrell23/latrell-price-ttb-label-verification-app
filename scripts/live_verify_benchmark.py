#!/usr/bin/env python3
import argparse
import json
import statistics
import time
from collections import Counter
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


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((percent / 100) * (len(ordered) - 1))
    return ordered[index]


def summarize(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": statistics.median(values) if values else None,
        "p95": percentile(values, 95),
        "max": max(values) if values else None,
    }


def post_verify(
    client: httpx.Client,
    base_url: str,
    image_path: Path,
    image_bytes: bytes,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        response = client.post(
            f"{base_url}/verify",
            data=APPLICATION_DATA,
            files={"image": (image_path.name, image_bytes, "image/jpeg")},
            headers={"Accept": "application/json"},
        )
    except httpx.TimeoutException as exc:
        return {
            "status_code": "client_timeout",
            "content_type": None,
            "body_kind": "exception",
            "error_code": type(exc).__name__,
            "body_preview": str(exc),
            "wall_ms": (time.perf_counter() - started_at) * 1000,
            "latency_ms": None,
            "overall_verdict": None,
        }
    except httpx.HTTPError as exc:
        return {
            "status_code": "client_error",
            "content_type": None,
            "body_kind": "exception",
            "error_code": type(exc).__name__,
            "body_preview": str(exc),
            "wall_ms": (time.perf_counter() - started_at) * 1000,
            "latency_ms": None,
            "overall_verdict": None,
        }

    wall_ms = (time.perf_counter() - started_at) * 1000
    content_type = response.headers.get("content-type", "")

    try:
        payload = response.json()
        body_kind = "json"
    except json.JSONDecodeError:
        payload = None
        body_kind = "non_json"

    error = payload.get("error") if isinstance(payload, dict) else None
    error_code = error.get("code") if isinstance(error, dict) else None
    return {
        "status_code": response.status_code,
        "content_type": content_type,
        "body_kind": body_kind,
        "error_code": error_code,
        "body_preview": (
            None if body_kind == "json" else response.text[:200].replace("\n", " ")
        ),
        "wall_ms": wall_ms,
        "latency_ms": (
            payload.get("latency_ms") if isinstance(payload, dict) else None
        ),
        "overall_verdict": (
            payload.get("overall_verdict") if isinstance(payload, dict) else None
        ),
    }


def counted(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key)) for record in records).items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the deployed /verify endpoint and classify failures."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE_PATH)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    image_bytes = args.image.read_bytes()
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=args.timeout) as client:
        health = client.get(f"{base_url}/health")
        health.raise_for_status()
        for _ in range(args.warmups):
            post_verify(client, base_url, args.image, image_bytes)
        for run_index in range(args.runs):
            record = post_verify(client, base_url, args.image, image_bytes)
            record["run_index"] = run_index
            records.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)

    successful = [
        record
        for record in records
        if record["status_code"] == 200
        and isinstance(record["latency_ms"], (int, float))
    ]
    failed = [record for record in records if record["status_code"] != 200]
    summary = {
        "base_url": base_url,
        "runs": args.runs,
        "warmups": args.warmups,
        "success_count": len(successful),
        "status_counts": counted(records, "status_code"),
        "error_code_counts": counted(failed, "error_code"),
        "failure_content_type_counts": counted(failed, "content_type"),
        "failure_body_kind_counts": counted(failed, "body_kind"),
        "api_latency_ms": summarize(
            [float(record["latency_ms"]) for record in successful]
        ),
        "wall_latency_ms": summarize(
            [float(record["wall_ms"]) for record in successful]
        ),
        "verdict_counts": counted(successful, "overall_verdict"),
    }
    print(json.dumps({"summary": summary}, indent=2, sort_keys=True))
    return 0 if len(successful) == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
