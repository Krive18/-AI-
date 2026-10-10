from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.v1.router import router as v1_router
from app.core.config import Settings
from app.core.database import DatabaseManager
from app.core.errors import AppError
from app.core.logging import request_id_context
from app.core.redis import RedisManager


class DependencyManager(Protocol):
    def ping(self) -> Awaitable[object]: ...

    def close(self) -> Awaitable[None]: ...


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_context.reset(context_token)
        response.headers["X-Request-Id"] = request_id
        settings = request.app.state.settings
        api_prefix = settings.api_prefix
        if request.url.path.startswith(api_prefix):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=()"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
            if settings.app_env == "production":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
        auth_prefix = f"{api_prefix}/auth"
        if request.url.path.startswith(auth_prefix):
            response.headers["Cache-Control"] = "no-store"
        return response


def error_response(error: AppError, request: Request) -> JSONResponse:
    request_id = request.state.request_id
    response = JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "requestId": request_id,
                "details": error.details,
            }
        },
    )
    response.headers["X-Request-Id"] = request_id
    auth_prefix = f"{request.app.state.settings.api_prefix}/auth"
    if request.url.path.startswith(auth_prefix):
        response.headers["Cache-Control"] = "no-store"
    return response


def create_app(
    settings: Settings | None = None,
    *,
    database_manager: DependencyManager | None = None,
    redis_manager: DependencyManager | None = None,
) -> FastAPI:
    app_settings = settings or Settings()  # type: ignore[call-arg]
    database = database_manager or DatabaseManager(app_settings)
    redis = redis_manager or RedisManager(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            try:
                await database.close()
            finally:
                await redis.close()

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.database_manager = database
    app.state.redis_manager = redis
    app.state.local_storage_root = str(app_settings.private_storage_root)
    if app_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        return error_response(error, request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, _: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            AppError(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                status_code=422,
            ),
            request,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, _error: Exception
    ) -> JSONResponse:
        return error_response(
            AppError(
                code="INTERNAL_SERVER_ERROR",
                message="Internal server error",
                status_code=500,
            ),
            request,
        )

    app.include_router(v1_router, prefix=app_settings.api_prefix)
    _mount_frontend(app, app_settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist
    if dist is None or not dist.is_dir():
        return
    dist_root = dist.resolve()
    index_html = dist_root / "index.html"
    if not index_html.is_file():
        return
    assets = dist_root / "assets"
    if assets.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets),
            name="frontend-assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith(settings.api_prefix.lstrip("/")):
            raise AppError("NOT_FOUND", "接口不存在", status_code=404)
        if full_path:
            candidate = (dist_root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
        return FileResponse(index_html)
