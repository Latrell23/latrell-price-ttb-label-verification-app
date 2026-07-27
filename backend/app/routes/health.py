import os
from datetime import datetime, timezone

from fastapi import APIRouter


router = APIRouter()


def _vision_configured() -> bool:
    """Return whether the deployed vision provider has usable credentials."""
    return bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))


@router.get("/health")
async def health() -> dict[str, str | bool]:
    """Return a lightweight service health payload."""
    return {
        "status": "healthy",
        "service": "ttb-label-reviewer-api",
        "environment": os.getenv("APP_ENV", "local"),
        "vision_configured": _vision_configured(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
