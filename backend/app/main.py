import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _split_env_list(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="TTB Label Verification API")

    allowed_origins = _split_env_list(
        os.getenv("ALLOWED_ORIGINS", "http://localhost:5173", "*")
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "ttb-label-verification-api",
            "environment": os.getenv("APP_ENV", "local"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    return app


app = create_app()
