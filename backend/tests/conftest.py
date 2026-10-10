import base64
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


class DependencyManager:
    def __init__(self) -> None:
        self.ping = AsyncMock(return_value=None)
        self.close = AsyncMock(return_value=None)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        redis_url="redis://127.0.0.1:6379/0",
        redis_protocol=2,
        session_hash_key="test-session-hash-key-that-is-at-least-32-bytes",
        provider_secret_encryption_key=base64.urlsafe_b64encode(
            bytes(range(32))
        ).decode(),
        allowed_origins=["http://127.0.0.1:5173"],
    )


@pytest.fixture
def database_manager() -> DependencyManager:
    return DependencyManager()


@pytest.fixture
def redis_manager() -> DependencyManager:
    return DependencyManager()


@pytest.fixture
def app(
    settings: Settings,
    database_manager: DependencyManager,
    redis_manager: DependencyManager,
) -> FastAPI:
    return create_app(
        settings,
        database_manager=database_manager,
        redis_manager=redis_manager,
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client
