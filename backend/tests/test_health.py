import asyncio

import httpx
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
    assert body["service"] == "ttb-label-reviewer-api"
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


def test_app_exposes_only_health_and_review_api_routes() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])

    assert paths == {
        "/health",
        "/review/labels",
        "/review/labels/{label_id}/verify",
        "/review/verify",
    }
    assert "/verify" not in paths
    assert "/verify/batch" not in paths
    assert "/verify/batch/stream" not in paths


@pytest.mark.parametrize(
    "path",
    ["/verify", "/verify/batch", "/verify/batch/stream"],
)
def test_legacy_upload_endpoints_return_not_found(path: str) -> None:
    async def post_legacy_path() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(path)

    response = asyncio.run(post_legacy_path())
    assert response.status_code == 404
