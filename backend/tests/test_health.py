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
