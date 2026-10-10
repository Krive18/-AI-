import base64
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.redis import RedisManager


def settings(environment: str, protocol: int) -> Settings:
    return Settings(
        app_env=environment,
        database_url="mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        redis_url="redis://127.0.0.1:6379/0",
        redis_protocol=protocol,
        session_cookie_name=(
            "__Host-ai_translation_session"
            if environment == "production"
            else "ai_translation_session"
        ),
        admin_session_cookie_name=(
            "__Host-ai_translation_admin_session"
            if environment == "production"
            else "ai_translation_admin_session"
        ),
        session_cookie_secure=environment == "production",
        session_hash_key="a-test-key-that-is-at-least-32-bytes-long",
        provider_secret_encryption_key=base64.urlsafe_b64encode(
            bytes(range(32))
        ).decode(),
        allowed_origins=["https://translation.example.test"],
    )


async def test_local_redis_readiness_does_not_require_a_modern_server() -> None:
    manager = RedisManager(settings("local", 2))
    manager.client = AsyncMock()

    await manager.ping()

    manager.client.ping.assert_awaited_once()
    manager.client.info.assert_not_awaited()


async def test_production_accepts_redis_7_2_or_newer() -> None:
    manager = RedisManager(settings("production", 3))
    manager.client = AsyncMock()
    manager.client.info.return_value = {"redis_version": "7.2.5"}

    await manager.ping()
    await manager.ping()

    assert manager.client.ping.await_count == 2
    manager.client.info.assert_awaited_once_with(section="server")


async def test_production_rejects_redis_older_than_7_2() -> None:
    manager = RedisManager(settings("production", 3))
    manager.client = AsyncMock()
    manager.client.info.return_value = {"redis_version": "7.0.15"}

    with pytest.raises(RuntimeError, match="Redis 7.2 or newer"):
        await manager.ping()
