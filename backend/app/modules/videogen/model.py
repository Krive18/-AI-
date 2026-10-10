from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, TINYINT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VideoJobStatus(IntEnum):
    PENDING = 1
    RUNNING = 2
    SUCCEEDED = 3
    FAILED = 4


class VideoGenerationJob(Base):
    __tablename__ = "video_generation"
    __table_args__ = (
        CheckConstraint("size IN ('480p','720p')", name="ck_video_generation_size"),
        CheckConstraint(
            "duration_seconds IN (5,10,15,20,25,30)",
            name="ck_video_generation_duration",
        ),
        CheckConstraint("tier IN (1,2,3)", name="ck_video_generation_tier"),
        CheckConstraint("status IN (1,2,3,4)", name="ck_video_generation_status"),
        Index("uk_video_generation_public_id", "public_id", unique=True),
        Index(
            "idx_video_generation_account_created",
            "account_id",
            "created_at",
        ),
        {
            "comment": "AI video generation jobs and their prompt settings",
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
        VARCHAR(2000), nullable=False, comment="Video prompt"
    )
    size: Mapped[str] = mapped_column(
        VARCHAR(8), nullable=False, comment="Requested video resolution 480p or 720p"
    )
    duration_seconds: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        comment="Requested video duration in seconds",
    )
    tier: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        comment="Quality tier 1 standard 2 fast 3 mini",
    )
    reference_object_key: Mapped[str | None] = mapped_column(
        VARCHAR(512),
        nullable=True,
        comment="Private storage object key of the first-frame reference image",
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
