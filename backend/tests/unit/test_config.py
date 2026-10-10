import pytest

from app.core.config import Settings


def valid_production_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        "redis_url": "redis://127.0.0.1:6379/0",
        "redis_protocol": 3,
        "session_cookie_name": "__Host-ai_translation_session",
        "admin_session_cookie_name": "__Host-ai_translation_admin_session",
        "session_cookie_secure": True,
        "session_hash_key": "a-test-key-that-is-at-least-32-bytes-long",
        "allowed_origins": ["https://translation.example.test"],
    }
    values.update(overrides)
    return values


def test_production_rejects_insecure_cookie() -> None:
    with pytest.raises(ValueError, match="secure cookie"):
        Settings(**valid_production_values(session_cookie_secure=False))


def test_production_rejects_unprefixed_cookie_name() -> None:
    with pytest.raises(ValueError, match="__Host-"):
        Settings(
            **valid_production_values(session_cookie_name="ai_translation_session")
        )


def test_production_rejects_unprefixed_admin_cookie_name() -> None:
    with pytest.raises(ValueError, match="__Host- admin cookie name"):
        Settings(
            **valid_production_values(
                admin_session_cookie_name="ai_translation_admin_session"
            )
        )


@pytest.mark.parametrize("origins", [[], ["*"]])
def test_production_rejects_non_explicit_origins(origins: list[str]) -> None:
    with pytest.raises(ValueError, match="explicit origins"):
        Settings(**valid_production_values(allowed_origins=origins))


def test_production_allows_empty_origins_when_hosting_frontend() -> None:
    settings = Settings(
        **valid_production_values(
            allowed_origins=[], frontend_dist="/srv/ai-translation/frontend/dist"
        )
    )

    assert settings.allowed_origins == []


def test_production_rejects_short_session_hash_key() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(**valid_production_values(session_hash_key="too-short"))


def test_production_rejects_local_redis_protocol() -> None:
    with pytest.raises(ValueError, match="RESP3"):
        Settings(**valid_production_values(redis_protocol=2))


def test_local_accepts_resp2_for_legacy_redis() -> None:
    settings = Settings(
        app_env="local",
        database_url="mysql+asyncmy://app:test@127.0.0.1:3306/test_db",
        redis_url="redis://127.0.0.1:6379/0",
        redis_protocol=2,
        session_hash_key="local-test-session-key",
    )

    assert settings.redis_protocol == 2
