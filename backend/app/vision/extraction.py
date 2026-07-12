import asyncio
import concurrent.futures

from app.verification.models import ExtractedLabel
from app.vision.constants import DEFAULT_TIMEOUT_SECONDS
from app.vision.errors import VisionAPIError
from app.vision.protocols import VisionService


async def extract_label_with_timeout(
    vision_service: VisionService,
    image_bytes: bytes,
    content_type: str | None,
    executor: concurrent.futures.ThreadPoolExecutor,
    timeout_seconds: float | None = None,
) -> ExtractedLabel:
    """Run blocking extraction in an executor within the configured time budget."""
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    future = executor.submit(vision_service.extract_label, image_bytes, content_type)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    while not future.done():
        if loop.time() >= deadline:
            future.cancel()
            raise VisionAPIError("Vision model request timed out")
        await asyncio.sleep(0.001)

    try:
        return future.result()
    except (TimeoutError, concurrent.futures.TimeoutError) as exc:
        future.cancel()
        raise VisionAPIError("Vision model request timed out") from exc


def extract_label_with_timeout_sync(
    vision_service: VisionService,
    image_bytes: bytes,
    content_type: str | None,
    timeout_seconds: float | None = None,
) -> ExtractedLabel:
    """Run blocking extraction synchronously within the configured time budget."""
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(vision_service.extract_label, image_bytes, content_type)

    try:
        return future.result(timeout=timeout_seconds)
    except (TimeoutError, concurrent.futures.TimeoutError) as exc:
        future.cancel()
        raise VisionAPIError("Vision model request timed out") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
