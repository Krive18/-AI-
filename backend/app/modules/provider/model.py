from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.dialects.mysql import (
    BIGINT,
    CHAR,
    DATETIME,
    JSON,
    TINYINT,
    VARBINARY,
    VARCHAR,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProviderCapability(IntEnum):
    ASR = 1
    TRANSLATION = 2
    TTS = 3
    SIMULTANEOUS_INTERPRETATION = 4
    IMAGE_GENERATION = 5
    SUBTITLE_OCR = 6
    VIDEO_GENERATION = 7


class ProviderStatus(IntEnum):
    ENABLED = 1
    DISABLED = 2


class ProviderConfig(Base):
    __tablename__ = "provider_config"
    __table_args__ = (
        CheckConstraint(
            "capability IN (1,2,3,4,5,6,7)", name="ck_provider_config_capability"
        ),
        CheckConstraint("status IN (1,2)", name="ck_provider_config_status"),
        Index("uk_provider_config_public_id", "public_id", unique=True),
        Index("uk_provider_config_code", "provider_code", unique=True),
        Index(
            "idx_provider_config_capability_status_priority",
            "capability",
            "status",
            "priority",
        ),
        {
            "comment": "Logical AI provider routing configuration",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_engine": "InnoDB",
        },
    )
    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )
    public_id: Mapped[str] = mapped_column(
        CHAR(26), nullable=False, comment="Public ULID identifier"
    )
    provider_code: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Stable provider routing code"
    )
    display_name: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Administrator display name"
    )
    capability: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation 6 subtitle OCR 7 video generation",
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Provider enabled state",
    )
    priority: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("100"),
        comment="Lower route priority wins",
    )
    supported_locales_json: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="Supported target locales snapshot"
    )
    active_version_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="Logical active provider version id",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC last update time"
    )


class ProviderVersion(Base):
    __tablename__ = "provider_version"
    __table_args__ = (
        CheckConstraint("status IN (1,2)", name="ck_provider_version_status"),
        Index("uk_provider_version_public_id", "public_id", unique=True),
        Index(
            "uk_provider_version_config_no",
            "provider_config_id",
            "version_no",
            unique=True,
        ),
        {
            "comment": "Immutable model endpoint and encrypted credential version",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_engine": "InnoDB",
        },
    )
    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )
    public_id: Mapped[str] = mapped_column(
        CHAR(26), nullable=False, comment="Public ULID identifier"
    )
    provider_config_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical provider config id"
    )
    version_no: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="Monotonic provider version number",
    )
    model_name: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Provider model identifier"
    )
    endpoint_url: Mapped[str] = mapped_column(
        VARCHAR(512), nullable=False, comment="Provider API endpoint"
    )
    timeout_ms: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="External request timeout in milliseconds",
    )
    config_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Non-secret immutable provider options"
    )
    encrypted_secret: Mapped[bytes] = mapped_column(
        VARBINARY(4096),
        nullable=False,
        comment="Envelope encrypted provider credential",
    )
    encryption_key_id: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Credential encryption key identifier"
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Version enabled state",
    )
    created_by: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
