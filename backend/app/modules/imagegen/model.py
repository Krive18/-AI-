from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, TINYINT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ImageJobStatus(IntEnum):
    PENDING = 1
    RUNNING = 2
    SUCCEEDED = 3
    FAILED = 4


class ImageGenerationJob(Base):
    __tablename__ = "image_generation"
    __table_args__ = (
        CheckConstraint("count BETWEEN 1 AND 3", name="ck_image_generation_count"),
        CheckConstraint(
            "reference_count BETWEEN 0 AND 3",
            name="ck_image_generation_reference_count",
        ),
        CheckConstraint("status IN (1,2,3,4)", name="ck_image_generation_status"),
        Index("uk_image_generation_public_id", "public_id", unique=True),
        Index(
            "idx_image_generation_account_created",
            "account_id",
            "created_at",
        ),
        {
            "comment": "AI image generation jobs and their prompt settings",
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
    account_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"
    )
    prompt: Mapped[str] = mapped_column(
        VARCHAR(2000), nullable=False, comment="Image prompt"
    )
    size: Mapped[str] = mapped_column(
        VARCHAR(8), nullable=False, comment="Requested image size"
    )
    count: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        comment="Requested image count from 1 to 3",
    )
    reference_count: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        comment="Reference image count from 0 to 3",
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="1 pending 2 running 3 succeeded 4 failed",
    )
    error_code: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Stable failure code"
    )
    error_message: Mapped[str | None] = mapped_column(
        VARCHAR(512), nullable=True, comment="Safe displayable failure message"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC terminal completion time"
    )
