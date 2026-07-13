import asyncio

from fastapi.middleware.cors import CORSMiddleware

from app.main import create_app


def test_health_returns_readiness_payload(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "healthy"
    assert body["service"] == "ttb-label-verification-api"
    assert body["vision_configured"] is True
    assert "checked_at" in body


def test_health_reports_unconfigured_vision(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "healthy"
    assert body["vision_configured"] is False


def test_cors_uses_env_origin_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://ttb-label-frontend.vercel.app")
    app = create_app()

    cors_middleware = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )

    assert "https://ttb-label-frontend.vercel.app" in cors_middleware.kwargs[
        "allow_origins"
    ]


def test_cors_does_not_hardcode_deployed_frontend_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    app = create_app()

    cors_middleware = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )

    assert "https://ttb-label-frontend.vercel.app" not in cors_middleware.kwargs[
        "allow_origins"
    ]
