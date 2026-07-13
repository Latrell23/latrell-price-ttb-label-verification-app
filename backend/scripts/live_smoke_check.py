import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from scripts.run_vision_sample import SAMPLE_WARNING, _create_sample_image


DEFAULT_BASE_URL = "https://latrell-price-ttb-label-verification-app.onrender.com"


APPLICATION_DATA = {
    "brand_name": "Acme Estate",
    "class_type": "Red Wine",
    "abv": "13.5%",
    "net_contents": "750 mL",
    "producer": "Acme Cellars",
    "country_of_origin": "United States",
    "government_warning": SAMPLE_WARNING,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a deployed /verify smoke check with a generated sample label."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    image_path = _create_sample_image()

    started_at = time.perf_counter()
    with image_path.open("rb") as image:
        response = httpx.post(
            f"{base_url}/verify",
            data=APPLICATION_DATA,
            files={"image": ("ttb_sample_label.jpg", image, "image/jpeg")},
            headers={"Accept": "application/json"},
            timeout=args.timeout,
        )
    latency_ms = (time.perf_counter() - started_at) * 1000

    payload: dict[str, Any]
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"raw_body": response.text}

    summary = {
        "base_url": base_url,
        "status_code": response.status_code,
        "latency_ms": round(latency_ms, 2),
        "response_keys": sorted(payload.keys()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if response.status_code != 200:
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1

    if not _is_success_shape(payload):
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1

    return 0


def _is_success_shape(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("results"), list)
        and isinstance(payload.get("overall_verdict"), str)
        and isinstance(payload.get("latency_ms"), (int, float))
    )


if __name__ == "__main__":
    raise SystemExit(main())
