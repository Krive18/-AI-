from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


class ClosingManager:
    def __init__(self, close_error: RuntimeError | None = None) -> None:
        self.close_error = close_error
        self.closed = False

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


async def test_liveness_returns_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-Id"]


async def test_api_responses_include_baseline_security_headers(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


async def test_validation_error_uses_the_unified_error_envelope(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/validation-error")
    async def validation_error(value: int) -> dict[str, int]:
        return {"value": value}

    response = await client.get("/validation-error", params={"value": "invalid"})

    request_id = response.headers["X-Request-Id"]
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "requestId": request_id,
            "details": {},
        }
    }


async def test_unhandled_error_uses_a_request_id_and_unified_envelope(
    app: FastAPI,
) -> None:
    @app.get("/unhandled-error")
    async def unhandled_error() -> None:
        raise RuntimeError("internal failure must not be exposed")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/unhandled-error")

    request_id = response.headers["X-Request-Id"]
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Internal server error",
            "requestId": request_id,
            "details": {},
        }
    }
    assert "internal failure must not be exposed" not in response.text


async def test_allowed_cors_preflight_has_a_request_id(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert response.headers["X-Request-Id"]


async def test_rejected_cors_preflight_has_a_request_id(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "https://not-allowed.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.headers["X-Request-Id"]


async def test_readiness_returns_ok_when_dependencies_are_available(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_database_failure(
    client: AsyncClient, database_manager: object
) -> None:
    database_manager.ping = AsyncMock(side_effect=RuntimeError("database unavailable"))

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    request_id = response.headers["X-Request-Id"]
    assert response.json() == {
        "error": {
            "code": "SERVICE_NOT_READY",
            "message": "Service is not ready",
            "requestId": request_id,
            "details": {},
        }
    }
    assert "database unavailable" not in response.text


async def test_readiness_reports_redis_failure(
    client: AsyncClient, redis_manager: object
) -> None:
    redis_manager.ping = AsyncMock(side_effect=RuntimeError("redis unavailable"))

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    request_id = response.headers["X-Request-Id"]
    assert response.json() == {
        "error": {
            "code": "SERVICE_NOT_READY",
            "message": "Service is not ready",
            "requestId": request_id,
            "details": {},
        }
    }
    assert "redis unavailable" not in response.text


async def test_lifespan_closes_both_managers(
    settings: Settings,
) -> None:
    database_manager = ClosingManager()
    redis_manager = ClosingManager()
    app = create_app(
        settings,
        database_manager=database_manager,
        redis_manager=redis_manager,
    )

    async with app.router.lifespan_context(app):
        pass

    assert database_manager.closed
    assert redis_manager.closed


async def test_lifespan_closes_redis_when_database_close_fails(
    settings: Settings,
) -> None:
    database_manager = ClosingManager(RuntimeError("database close failed"))
    redis_manager = ClosingManager()
    app = create_app(
        settings,
        database_manager=database_manager,
        redis_manager=redis_manager,
    )

    with pytest.raises(RuntimeError, match="database close failed"):
        async with app.router.lifespan_context(app):
            pass

    assert database_manager.closed
    assert redis_manager.closed


async def test_lifespan_propagates_redis_close_failure_after_database_close(
    settings: Settings,
) -> None:
    database_manager = ClosingManager()
    redis_manager = ClosingManager(RuntimeError("redis close failed"))
    app = create_app(
        settings,
        database_manager=database_manager,
        redis_manager=redis_manager,
    )

    with pytest.raises(RuntimeError, match="redis close failed"):
        async with app.router.lifespan_context(app):
            pass

    assert database_manager.closed
    assert redis_manager.closed
