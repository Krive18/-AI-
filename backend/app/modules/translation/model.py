from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, INTEGER, TINYINT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectStatus(IntEnum):
    DRAFT = 1
    UPLOADING = 2
    VALIDATING = 3
    EXTRACTING_AUDIO = 4
    RECOGNIZING = 5
    PROCESSING = 6
    SUCCEEDED = 7
    PARTIALLY_SUCCEEDED = 8
    FAILED = 9
    CANCEL_REQUESTED = 10
    CANCELLED = 11


class TaskStatus(IntEnum):
    QUEUED = 1
    TRANSLATING = 2
    SYNTHESIZING = 3
    RENDERING = 4
    SUCCEEDED = 5
    FAILED = 6
    CANCEL_REQUESTED = 7
    CANCELLED = 8


class TaskStage(IntEnum):
    QUEUED = 1
    TRANSLATING = 2
    SYNTHESIZING = 3
    RENDERING = 4
    COMPLETED = 5


class TranslationProject(Base):
    __tablename__ = "translation_project"
    __table_args__ = (
        CheckConstraint(
            "status IN (1,2,3,4,5,6,7,8,9,10,11)", name="ck_translation_project_status"
        ),
        CheckConstraint(
            "translation_mode IN ('professional','youdao','subtitle')",
            name="ck_translation_project_mode",
        ),
        CheckConstraint(
            "source_size_bytes >= 0", name="ck_translation_project_source_size"
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name="ck_translation_project_progress"
        ),
        CheckConstraint(
            "estimated_cost_microunit >= 0",
            name="ck_translation_project_estimated_cost",
        ),
        CheckConstraint(
            "actual_cost_microunit >= 0", name="ck_translation_project_actual_cost"
        ),
        Index("uk_translation_project_public_id", "public_id", unique=True),
        Index("idx_translation_project_creator_created", "created_by", "created_at"),
        Index("idx_translation_project_status_created", "status", "created_at"),
        {
            "comment": "One uploaded source video and its translation work",
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
    created_by: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"
    )
    name: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Internal project name"
    )
    source_filename: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment="Original uploaded filename"
    )
    source_content_type: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Declared source content type"
    )
    source_object_key: Mapped[str] = mapped_column(
        VARCHAR(512), nullable=False, comment="Private source object key"
    )
    source_sha256: Mapped[str | None] = mapped_column(
        CHAR(64), nullable=True, comment="Verified source SHA-256"
    )
    source_size_bytes: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Verified source size in bytes"
    )
    source_duration_ms: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="Verified source duration in milliseconds",
    )
    source_container: Mapped[str | None] = mapped_column(
        VARCHAR(32), nullable=True, comment="Verified source container"
    )
    source_video_codec: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Verified source video codec"
    )
    source_audio_codec: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Verified source audio codec"
    )
    translation_mode: Mapped[str] = mapped_column(
        VARCHAR(24),
        nullable=False,
        server_default=text("'professional'"),
        comment="Selected processing path: professional, youdao, or subtitle",
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Project workflow status",
    )
    progress_percent: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Aggregate progress from 0 to 100",
    )
    estimated_cost_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Estimated cost in micro currency units",
    )
    actual_cost_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Actual cost in micro currency units",
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC cancellation request time"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC terminal completion time"
    )
    version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Optimistic lock version",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC last update time"
    )


class TranslationTask(Base):
    __tablename__ = "translation_task"
    __table_args__ = (
        CheckConstraint(
            "status IN (1,2,3,4,5,6,7,8)", name="ck_translation_task_status"
        ),
        CheckConstraint(
            "target_locale IN ('en-US','ja-JP','ko-KR','vi-VN','ms-MY','th-TH','en-SG','fil-PH','de-DE','fr-FR')",
            name="ck_translation_task_target_locale",
        ),
        CheckConstraint("retry_count >= 0", name="ck_translation_task_retry_count"),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name="ck_translation_task_progress"
        ),
        CheckConstraint(
            "estimated_cost_microunit >= 0", name="ck_translation_task_estimated_cost"
        ),
        CheckConstraint(
            "actual_cost_microunit >= 0", name="ck_translation_task_actual_cost"
        ),
        Index("uk_translation_task_public_id", "public_id", unique=True),
        Index(
            "uk_translation_task_project_locale",
            "project_id",
            "target_locale",
            unique=True,
        ),
        Index(
            "idx_translation_task_project_status_created",
            "project_id",
            "status",
            "created_at",
        ),
        {
            "comment": "One independent target locale translation task",
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
        BIGINT(unsigned=True), nullable=False, comment="Logical parent project id"
    )
    target_locale: Mapped[str] = mapped_column(
        VARCHAR(16), nullable=False, comment="BCP 47 output locale"
    )
    voice_id: Mapped[str | None] = mapped_column(
        VARCHAR(128), nullable=True, comment="Requested target voice identifier"
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Task workflow status",
    )
    stage: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Current processing stage",
    )
    progress_percent: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Task progress from 0 to 100",
    )
    retry_count: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Completed retry attempts",
    )
    max_retries: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("3"),
        comment="Maximum automatic retry attempts",
    )
    error_code: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Stable failure code"
    )
    error_message: Mapped[str | None] = mapped_column(
        VARCHAR(512), nullable=True, comment="Safe displayable failure message"
    )
    estimated_cost_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Estimated cost in micro currency units",
    )
    actual_cost_microunit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
        comment="Actual cost in micro currency units",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC terminal completion time"
    )
    version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Optimistic lock version",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC last update time"
    )
