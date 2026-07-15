from collections.abc import Callable
from functools import lru_cache

from app.vision.protocols import VisionService
from app.vision.providers import OpenAIVisionService


VisionServiceDependency = VisionService | Callable[[], VisionService]


@lru_cache(maxsize=1)
def get_vision_service() -> VisionService:
    """Return one production vision service per backend process."""
    return OpenAIVisionService()


def close_vision_service() -> None:
    """Close and clear the process-scoped production vision service."""
    if get_vision_service.cache_info().currsize:
        service = get_vision_service()
        close = getattr(service, "close", None)
        if callable(close):
            close()
    get_vision_service.cache_clear()


def resolve_vision_service(
    vision_service: VisionServiceDependency,
) -> VisionService:
    """Resolve a vision dependency from an instance, class, or callable factory."""
    if isinstance(vision_service, type):
        return vision_service()

    if hasattr(vision_service, "extract_label"):
        return vision_service

    return vision_service()
