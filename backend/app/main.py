import os
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.health import router as health_router
from app.routes.verify import router as verify_router


def _split_env_list(value: str) -> list[str]:
    """Return a cleaned list from a comma-separated environment variable."""
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def create_app() -> FastAPI:
    """Create and configure the TTB label verification API."""
    app = FastAPI(title="TTB Label Verification API")

    # Configure browser access for the static frontend.
    allowed_origins = _split_env_list(
        os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
    )
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
