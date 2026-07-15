import asyncio

import pytest
from fastapi.middleware.cors import CORSMiddleware

from app.main import create_app


def test_health_returns_readiness_payload(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "healthy"
    assert body["service"] == "ttb-label-verification-api"
    assert body["vision_configured"] is True
    assert "checked_at" in body


def test_health_reports_unconfigured_vision(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "healthy"
    assert body["vision_configured"] is False


@pytest.mark.parametrize("missing_variable", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_health_requires_key_and_model(monkeypatch, missing_variable) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.delenv(missing_variable, raising=False)
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

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


def test_app_lifespan_closes_shared_vision_service(monkeypatch) -> None:
    closed = False

    def close_service() -> None:
        nonlocal closed
        closed = True

    monkeypatch.setattr("app.main.close_vision_service", close_service)
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert closed is False

    asyncio.run(run_lifespan())

    assert closed is True
