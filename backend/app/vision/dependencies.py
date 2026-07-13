from collections.abc import Callable

from app.vision.protocols import VisionService
from app.vision.providers import GeminiVisionService


VisionServiceDependency = VisionService | Callable[[], VisionService]


def get_vision_service() -> Callable[[], VisionService]:
    """Return the default production vision service factory."""
    return GeminiVisionService


def resolve_vision_service(
    vision_service: VisionServiceDependency,
) -> VisionService:
    """Resolve a vision dependency from an instance, class, or callable factory."""
    if isinstance(vision_service, type):
        return vision_service()

    if hasattr(vision_service, "extract_label"):
        return vision_service

    return vision_service()
