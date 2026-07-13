import os
from datetime import datetime, timezone

from fastapi import APIRouter


router = APIRouter()


def _vision_configured() -> bool:
    """Return whether the deployed vision provider has usable credentials."""
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


@router.get("/health")
async def health() -> dict[str, str | bool]:
    """Return a lightweight service health payload."""
    return {
        "status": "healthy",
        "service": "ttb-label-verification-api",
        "environment": os.getenv("APP_ENV", "local"),
        "vision_configured": _vision_configured(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
