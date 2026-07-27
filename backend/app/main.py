import os
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.review import REVIEW_IMAGE_DIR
from app.routes.health import router as health_router
from app.routes.review import router as review_router
from app.vision.dependencies import close_vision_service


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Release process-scoped clients when the application shuts down."""
    try:
        yield
    finally:
        close_vision_service()


def create_app() -> FastAPI:
    """Create and configure the TTB label reviewer API."""
    app = FastAPI(title="TTB Label Reviewer API", lifespan=lifespan)

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
    app.include_router(review_router)
    app.mount(
        "/review/assets",
        StaticFiles(directory=str(REVIEW_IMAGE_DIR)),
        name="review_assets",
    )

    return app


app = create_app()
