import asyncio

from fastapi.middleware.cors import CORSMiddleware

from app.main import create_app


def test_health_returns_ok() -> None:
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "ok"
    assert body["service"] == "ttb-label-verification-api"
    assert "checked_at" in body


def test_cors_allows_deployed_frontend_when_env_has_existing_origin(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
    app = create_app()

    cors_middleware = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )

    assert "https://ttb-label-frontend.vercel.app" in cors_middleware.kwargs[
        "allow_origins"
    ]
