from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, JSON, TINYINT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UsageStatus(IntEnum):
    SUCCEEDED = 1
    FAILED = 2
    CANCELLED = 3


class ProviderPrice(Base):
    __tablename__ = "provider_price"
    __table_args__ = (
        CheckConstraint(
            "capability IN (1,2,3,4,5,6,7)", name="ck_provider_price_capability"
        ),
        CheckConstraint(
            "unit_price_microunit >= 0", name="ck_provider_price_unit_price"
        ),
        CheckConstraint("unit_size > 0", name="ck_provider_price_unit_size"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_provider_price_effective_range",
        ),
        Index("uk_provider_price_public_id", "public_id", unique=True),
        Index(
            "idx_provider_price_lookup",
            "provider_version_id",
            "capability",
            "model_name",
            "effective_from",
        ),
        {
            "comment": "Immutable provider price effective-dated records",
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
    provider_version_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="Logical immutable provider version id",
    )
    capability: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="Provider capability"
    )
    model_name: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Priced provider model"
    )
    target_locale: Mapped[str | None] = mapped_column(
        VARCHAR(16), nullable=True, comment="Optional locale-specific price"
    )
    billing_unit: Mapped[str] = mapped_column(
        VARCHAR(32), nullable=False, comment="Unit such as characters or milliseconds"
    )
    unit_size: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="Quantity covered by one price unit",
    )
    unit_price_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Price in micro currency units"
    )
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, comment="ISO 4217 currency code"
    )
    effective_from: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC inclusive price effective time"
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC exclusive price end time"
    )
    created_by: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )


class AiUsageRecord(Base):
    __tablename__ = "ai_usage_record"
    __table_args__ = (
        CheckConstraint(
            "capability IN (1,2,3,4,5,6,7)", name="ck_ai_usage_record_capability"
        ),
        CheckConstraint("status IN (1,2,3)", name="ck_ai_usage_record_status"),
        CheckConstraint("cost_microunit >= 0", name="ck_ai_usage_record_cost"),
        CheckConstraint("input_units >= 0", name="ck_ai_usage_record_input_units"),
        CheckConstraint("output_units >= 0", name="ck_ai_usage_record_output_units"),
        Index("uk_ai_usage_record_public_id", "public_id", unique=True),
        Index("uk_ai_usage_record_request", "request_id", unique=True),
        Index("idx_ai_usage_project_created", "project_id", "created_at"),
        Index("idx_ai_usage_provider_created", "provider_version_id", "created_at"),
        {
            "comment": "Append-only metered AI provider request records",
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
    project_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical project id"
    )
    task_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="Logical optional task id"
    )
    provider_version_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical provider version id"
    )
    request_id: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Idempotent external request identifier"
    )
    capability: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="Provider capability"
    )
    model_name: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Provider model snapshot"
    )
    target_locale: Mapped[str | None] = mapped_column(
        VARCHAR(16), nullable=True, comment="Output locale when applicable"
    )
    input_units: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Metered input quantity"
    )
    output_units: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Metered output quantity"
    )
    duration_ms: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="Provider request duration in milliseconds",
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="Usage outcome status"
    )
    unit_price_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Applied unit price snapshot"
    )
    cost_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Calculated immutable cost"
    )
    price_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, comment="Applied immutable price rule snapshot"
    )
    error_code: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Safe provider failure code"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
