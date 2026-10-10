from datetime import datetime
from enum import IntEnum

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.mysql import (
    BIGINT,
    CHAR,
    DATETIME,
    DECIMAL,
    JSON,
    TINYINT,
    VARCHAR,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AssetType(IntEnum):
    SOURCE_VIDEO = 1
    EXTRACTED_AUDIO = 2
    DUBBED_AUDIO = 3
    OUTPUT_VIDEO = 4
    SUBTITLE_SRT = 5


class MediaAsset(Base):
    __tablename__ = "media_asset"
    __table_args__ = (
        CheckConstraint("asset_type IN (1,2,3,4,5)", name="ck_media_asset_type"),
        CheckConstraint("size_bytes >= 0", name="ck_media_asset_size"),
        Index("uk_media_asset_public_id", "public_id", unique=True),
        Index(
            "idx_media_asset_project_type_created",
            "project_id",
            "asset_type",
            "created_at",
        ),
        Index(
            "idx_media_asset_task_type_created", "task_id", "asset_type", "created_at"
        ),
        {
            "comment": "Private source, intermediate, and output media objects",
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
        BIGINT(unsigned=True),
        nullable=True,
        comment="Logical optional translation task id",
    )
    asset_type: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="Media asset type"
    )
    object_key: Mapped[str] = mapped_column(
        VARCHAR(512), nullable=False, comment="Private object storage key"
    )
    content_type: Mapped[str] = mapped_column(
        VARCHAR(128), nullable=False, comment="Verified media content type"
    )
    sha256: Mapped[str | None] = mapped_column(
        CHAR(64), nullable=True, comment="SHA-256 digest"
    )
    size_bytes: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Object size in bytes"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="Media duration in milliseconds"
    )
    container: Mapped[str | None] = mapped_column(
        VARCHAR(32), nullable=True, comment="Media container"
    )
    video_codec: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Video codec"
    )
    audio_codec: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Audio codec"
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Verified stream metadata"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )


class SourceSegment(Base):
    __tablename__ = "source_segment"
    __table_args__ = (
        CheckConstraint(
            "start_ms >= 0 AND end_ms >= start_ms", name="ck_source_segment_timeline"
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="ck_source_segment_confidence",
        ),
        Index(
            "uk_source_segment_project_sequence",
            "project_id",
            "sequence_no",
            unique=True,
        ),
        {
            "comment": "Shared Chinese ASR timeline segment",
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
    project_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical project id"
    )
    sequence_no: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="One-based source segment order"
    )
    start_ms: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Start offset in milliseconds"
    )
    end_ms: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="End offset in milliseconds"
    )
    speaker_label: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Optional ASR speaker label"
    )
    source_text: Mapped[str] = mapped_column(
        VARCHAR(4096), nullable=False, comment="Recognized Chinese source text"
    )
    confidence: Mapped[float | None] = mapped_column(
        DECIMAL(5, 4), nullable=True, comment="ASR confidence from zero to one"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )


class SubtitleSegment(Base):
    __tablename__ = "subtitle_segment"
    __table_args__ = (
        Index(
            "uk_subtitle_segment_task_source",
            "task_id",
            "source_segment_id",
            unique=True,
        ),
        Index("idx_subtitle_segment_task_sequence", "task_id", "sequence_no"),
        {
            "comment": "One translated subtitle segment per task source segment",
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
    task_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical translation task id"
    )
    source_segment_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical source segment id"
    )
    sequence_no: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Target subtitle order"
    )
    translated_text: Mapped[str] = mapped_column(
        VARCHAR(4096), nullable=False, comment="Translated target locale text"
    )
    tts_text: Mapped[str | None] = mapped_column(
        VARCHAR(4096), nullable=True, comment="Normalized text sent to TTS"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )


class TaskEvent(Base):
    __tablename__ = "task_event"
    __table_args__ = (
        CheckConstraint(
            "progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100",
            name="ck_task_event_progress",
        ),
        Index("idx_task_event_task_created", "task_id", "created_at"),
        Index("idx_task_event_project_created", "project_id", "created_at"),
        {
            "comment": "Append-only workflow events and safe failures",
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
    project_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="Logical project id"
    )
    task_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="Logical optional task id"
    )
    event_type: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Stable workflow event code"
    )
    stage: Mapped[int | None] = mapped_column(
        TINYINT(unsigned=True), nullable=True, comment="Related project or task stage"
    )
    progress_percent: Mapped[int | None] = mapped_column(
        TINYINT(unsigned=True), nullable=True, comment="Observed progress from 0 to 100"
    )
    error_code: Mapped[str | None] = mapped_column(
        VARCHAR(64), nullable=True, comment="Stable safe failure code"
    )
    error_message: Mapped[str | None] = mapped_column(
        VARCHAR(512), nullable=True, comment="Safe displayable failure message"
    )
    details_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Redacted event details"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation time"
    )
