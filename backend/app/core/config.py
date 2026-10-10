import base64
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    app_name: str = "LinguaSphere API"
    api_prefix: str = "/api/v1"
    database_url: str
    redis_url: str
    redis_protocol: int = Field(default=3, ge=2, le=3)
    session_cookie_name: str = "ai_translation_session"
    admin_session_cookie_name: str = "ai_translation_admin_session"
    session_cookie_secure: bool = False
    session_hash_key: SecretStr
    provider_secret_encryption_key: SecretStr
    allowed_origins: list[str] = Field(default_factory=list)
    frontend_dist: Path | None = None
    private_storage_root: Path = Path(".ai_translation_private")
    worker_poll_interval_seconds: float = Field(default=2.0, gt=0, le=60)
    worker_lease_seconds: int = Field(default=1800, ge=60, le=7200)
    worker_max_concurrency: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production":
            if not self.session_cookie_secure:
                raise ValueError("production requires a secure cookie")
            if self.session_cookie_name != "__Host-ai_translation_session":
                raise ValueError("production requires the __Host- cookie name")
            if self.admin_session_cookie_name != "__Host-ai_translation_admin_session":
                raise ValueError("production requires the __Host- admin cookie name")
            if "*" in self.allowed_origins:
                raise ValueError("production requires explicit origins")
            if self.frontend_dist is None and not self.allowed_origins:
                raise ValueError(
                    "production requires explicit origins or a hosted frontend_dist"
                )
            if len(self.session_hash_key.get_secret_value().encode()) < 32:
                raise ValueError("session hash key must contain at least 32 bytes")
            try:
                provider_key = base64.urlsafe_b64decode(
                    self.provider_secret_encryption_key.get_secret_value().encode()
                )
            except ValueError as error:
                raise ValueError(
                    "production requires a base64 provider encryption key"
                ) from error
            if len(provider_key) != 32 or len(set(provider_key)) == 1:
                raise ValueError(
                    "production requires a strong independent provider encryption key"
                )
            if self.redis_protocol != 3:
                raise ValueError("production requires RESP3 and Redis 7.2+")
        return self
