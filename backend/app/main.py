import os
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.health import router as health_router
from app.routes.verify import router as verify_router


DEFAULT_LOCAL_ALLOWED_ORIGINS = (
    "http://localhost:5173",
)


def _split_env_list(value: str) -> list[str]:
    """Return a cleaned list from a comma-separated environment variable."""
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def _allowed_origins(value: str | None, app_env: str | None) -> list[str]:
    """Return configured origins, falling back to local defaults outside production."""
    configured_origins = _split_env_list(value or "")
    default_origins = (
        []
        if (app_env or "").strip().lower() == "production"
        else list(DEFAULT_LOCAL_ALLOWED_ORIGINS)
    )

    origins: list[str] = []
    for origin in [*default_origins, *configured_origins]:
        if origin not in origins:
            origins.append(origin)
    return origins


def create_app() -> FastAPI:
    """Create and configure the TTB label verification API."""
    app = FastAPI(title="TTB Label Verification API")

    # Configure browser access for the static frontend.
    allowed_origins = _allowed_origins(os.getenv("ALLOWED_ORIGINS"), os.getenv("APP_ENV"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Register public API routes.
    app.include_router(health_router)
    app.include_router(verify_router)

    return app


app = create_app()
