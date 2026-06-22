import os
from datetime import datetime, timezone

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Return a lightweight service health payload."""
    return {
        "status": "ok",
        "service": "ttb-label-verification-api",
        "environment": os.getenv("APP_ENV", "local"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
