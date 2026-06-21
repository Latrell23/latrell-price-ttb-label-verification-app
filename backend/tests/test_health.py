import asyncio

from app.main import create_app


def test_health_returns_ok() -> None:
    app = create_app()
    route = next(route for route in app.routes if route.path == "/health")

    body = asyncio.run(route.endpoint())

    assert body["status"] == "ok"
    assert body["service"] == "ttb-label-verification-api"
    assert "checked_at" in body
