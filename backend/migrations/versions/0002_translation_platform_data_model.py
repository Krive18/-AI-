"""Create translation platform business tables.

Revision ID: 0002_translation_data
Revises: 0001_accounts_and_audit
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002_translation_data"
down_revision: str | None = "0001_accounts_and_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def _id() -> sa.Column[object]:
    return sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="Primary key")


def _public_id() -> sa.Column[object]:
    return sa.Column("public_id", mysql.CHAR(26), nullable=False, comment="Public ULID identifier")


def _created_at() -> sa.Column[object]:
    return sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False, comment="UTC creation time")


def _updated_at() -> sa.Column[object]:
    return sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False, comment="UTC last update time")


def upgrade() -> None:
    op.create_table(
        "translation_project",
        _id(), _public_id(),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"),
        sa.Column("name", mysql.VARCHAR(128), nullable=False, comment="Internal project name"),
        sa.Column("source_filename", mysql.VARCHAR(255), nullable=False, comment="Original uploaded filename"),
        sa.Column("source_content_type", mysql.VARCHAR(128), nullable=False, comment="Declared source content type"),
        sa.Column("source_object_key", mysql.VARCHAR(512), nullable=False, comment="Private source object key"),
        sa.Column("source_sha256", mysql.CHAR(64), nullable=True, comment="Verified source SHA-256"),
        sa.Column("source_size_bytes", mysql.BIGINT(unsigned=True), nullable=False, comment="Verified source size in bytes"),
        sa.Column("source_duration_ms", mysql.BIGINT(unsigned=True), nullable=True, comment="Verified source duration in milliseconds"),
        sa.Column("source_container", mysql.VARCHAR(32), nullable=True, comment="Verified source container"),
        sa.Column("source_video_codec", mysql.VARCHAR(64), nullable=True, comment="Verified source video codec"),
        sa.Column("source_audio_codec", mysql.VARCHAR(64), nullable=True, comment="Verified source audio codec"),
        sa.Column("status", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Project workflow status"),
        sa.Column("progress_percent", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Aggregate progress from 0 to 100"),
        sa.Column("estimated_cost_microunit", mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Estimated cost in micro currency units"),
        sa.Column("actual_cost_microunit", mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Actual cost in micro currency units"),
        sa.Column("cancel_requested_at", mysql.DATETIME(fsp=3), nullable=True, comment="UTC cancellation request time"),
        sa.Column("completed_at", mysql.DATETIME(fsp=3), nullable=True, comment="UTC terminal completion time"),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Optimistic lock version"),
        _created_at(), _updated_at(),
        sa.CheckConstraint("status IN (1,2,3,4,5,6,7,8,9,10,11)", name="ck_translation_project_status"),
        sa.CheckConstraint("source_size_bytes >= 0", name="ck_translation_project_source_size"),
        sa.CheckConstraint("progress_percent BETWEEN 0 AND 100", name="ck_translation_project_progress"),
        sa.CheckConstraint("estimated_cost_microunit >= 0", name="ck_translation_project_estimated_cost"),
        sa.CheckConstraint("actual_cost_microunit >= 0", name="ck_translation_project_actual_cost"),
        comment="One uploaded source video and its translation work", **TABLE_OPTIONS,
    )
    op.create_index("uk_translation_project_public_id", "translation_project", ["public_id"], unique=True)
    op.create_index("idx_translation_project_creator_created", "translation_project", ["created_by", "created_at"])
    op.create_index("idx_translation_project_status_created", "translation_project", ["status", "created_at"])

    op.create_table(
        "translation_task",
        _id(), _public_id(),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical parent project id"),
        sa.Column("target_locale", mysql.VARCHAR(16), nullable=False, comment="BCP 47 output locale"),
        sa.Column("voice_id", mysql.VARCHAR(128), nullable=True, comment="Requested target voice identifier"),
        sa.Column("status", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Task workflow status"),
        sa.Column("stage", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Current processing stage"),
        sa.Column("progress_percent", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Task progress from 0 to 100"),
        sa.Column("retry_count", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Completed retry attempts"),
        sa.Column("max_retries", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("3"), comment="Maximum automatic retry attempts"),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True, comment="Stable failure code"),
        sa.Column("error_message", mysql.VARCHAR(512), nullable=True, comment="Safe displayable failure message"),
        sa.Column("estimated_cost_microunit", mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Estimated cost in micro currency units"),
        sa.Column("actual_cost_microunit", mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text("0"), comment="Actual cost in micro currency units"),
        sa.Column("completed_at", mysql.DATETIME(fsp=3), nullable=True, comment="UTC terminal completion time"),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Optimistic lock version"),
        _created_at(), _updated_at(),
        sa.CheckConstraint("status IN (1,2,3,4,5,6,7,8)", name="ck_translation_task_status"),
        sa.CheckConstraint("target_locale IN ('en-US','ja-JP','ko-KR','vi-VN','ms-MY','th-TH','en-SG','fil-PH')", name="ck_translation_task_target_locale"),
        sa.CheckConstraint("retry_count >= 0", name="ck_translation_task_retry_count"),
        sa.CheckConstraint("progress_percent BETWEEN 0 AND 100", name="ck_translation_task_progress"),
        sa.CheckConstraint("estimated_cost_microunit >= 0", name="ck_translation_task_estimated_cost"),
        sa.CheckConstraint("actual_cost_microunit >= 0", name="ck_translation_task_actual_cost"),
        comment="One independent target locale translation task", **TABLE_OPTIONS,
    )
    op.create_index("uk_translation_task_public_id", "translation_task", ["public_id"], unique=True)
    op.create_index("uk_translation_task_project_locale", "translation_task", ["project_id", "target_locale"], unique=True)
    op.create_index("idx_translation_task_project_status_created", "translation_task", ["project_id", "status", "created_at"])

    op.create_table(
        "media_asset",
        _id(), _public_id(),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical project id"),
        sa.Column("task_id", mysql.BIGINT(unsigned=True), nullable=True, comment="Logical optional translation task id"),
        sa.Column("asset_type", mysql.TINYINT(unsigned=True), nullable=False, comment="Media asset type"),
        sa.Column("object_key", mysql.VARCHAR(512), nullable=False, comment="Private object storage key"),
        sa.Column("content_type", mysql.VARCHAR(128), nullable=False, comment="Verified media content type"),
        sa.Column("sha256", mysql.CHAR(64), nullable=True, comment="SHA-256 digest"),
        sa.Column("size_bytes", mysql.BIGINT(unsigned=True), nullable=False, comment="Object size in bytes"),
        sa.Column("duration_ms", mysql.BIGINT(unsigned=True), nullable=True, comment="Media duration in milliseconds"),
        sa.Column("container", mysql.VARCHAR(32), nullable=True, comment="Media container"),
        sa.Column("video_codec", mysql.VARCHAR(64), nullable=True, comment="Video codec"),
        sa.Column("audio_codec", mysql.VARCHAR(64), nullable=True, comment="Audio codec"),
        sa.Column("metadata_json", mysql.JSON(), nullable=True, comment="Verified stream metadata"), _created_at(),
        sa.CheckConstraint("asset_type IN (1,2,3,4,5)", name="ck_media_asset_type"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_media_asset_size"),
        comment="Private source, intermediate, and output media objects", **TABLE_OPTIONS,
    )
    op.create_index("uk_media_asset_public_id", "media_asset", ["public_id"], unique=True)
    op.create_index("idx_media_asset_project_type_created", "media_asset", ["project_id", "asset_type", "created_at"])
    op.create_index("idx_media_asset_task_type_created", "media_asset", ["task_id", "asset_type", "created_at"])

    op.create_table(
        "source_segment",
        _id(),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical project id"),
        sa.Column("sequence_no", mysql.BIGINT(unsigned=True), nullable=False, comment="One-based source segment order"),
        sa.Column("start_ms", mysql.BIGINT(unsigned=True), nullable=False, comment="Start offset in milliseconds"),
        sa.Column("end_ms", mysql.BIGINT(unsigned=True), nullable=False, comment="End offset in milliseconds"),
        sa.Column("speaker_label", mysql.VARCHAR(64), nullable=True, comment="Optional ASR speaker label"),
        sa.Column("source_text", mysql.VARCHAR(4096), nullable=False, comment="Recognized Chinese source text"),
        sa.Column("confidence", mysql.DECIMAL(5, 4), nullable=True, comment="ASR confidence from zero to one"), _created_at(),
        sa.CheckConstraint("start_ms >= 0 AND end_ms >= start_ms", name="ck_source_segment_timeline"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_source_segment_confidence"),
        comment="Shared Chinese ASR timeline segment", **TABLE_OPTIONS,
    )
    op.create_index("uk_source_segment_project_sequence", "source_segment", ["project_id", "sequence_no"], unique=True)

    op.create_table(
        "subtitle_segment",
        _id(),
        sa.Column("task_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical translation task id"),
        sa.Column("source_segment_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical source segment id"),
        sa.Column("sequence_no", mysql.BIGINT(unsigned=True), nullable=False, comment="Target subtitle order"),
        sa.Column("translated_text", mysql.VARCHAR(4096), nullable=False, comment="Translated target locale text"),
        sa.Column("tts_text", mysql.VARCHAR(4096), nullable=True, comment="Normalized text sent to TTS"), _created_at(),
        comment="One translated subtitle segment per task source segment", **TABLE_OPTIONS,
    )
    op.create_index("uk_subtitle_segment_task_source", "subtitle_segment", ["task_id", "source_segment_id"], unique=True)
    op.create_index("idx_subtitle_segment_task_sequence", "subtitle_segment", ["task_id", "sequence_no"])

    op.create_table(
        "task_event",
        _id(),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical project id"),
        sa.Column("task_id", mysql.BIGINT(unsigned=True), nullable=True, comment="Logical optional task id"),
        sa.Column("event_type", mysql.VARCHAR(64), nullable=False, comment="Stable workflow event code"),
        sa.Column("stage", mysql.TINYINT(unsigned=True), nullable=True, comment="Related project or task stage"),
        sa.Column("progress_percent", mysql.TINYINT(unsigned=True), nullable=True, comment="Observed progress from 0 to 100"),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True, comment="Stable safe failure code"),
        sa.Column("error_message", mysql.VARCHAR(512), nullable=True, comment="Safe displayable failure message"),
        sa.Column("details_json", mysql.JSON(), nullable=True, comment="Redacted event details"), _created_at(),
        sa.CheckConstraint("progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100", name="ck_task_event_progress"),
        comment="Append-only workflow events and safe failures", **TABLE_OPTIONS,
    )
    op.create_index("idx_task_event_task_created", "task_event", ["task_id", "created_at"])
    op.create_index("idx_task_event_project_created", "task_event", ["project_id", "created_at"])

    op.create_table(
        "provider_config",
        _id(), _public_id(),
        sa.Column("provider_code", mysql.VARCHAR(64), nullable=False, comment="Stable provider routing code"),
        sa.Column("display_name", mysql.VARCHAR(128), nullable=False, comment="Administrator display name"),
        sa.Column("capability", mysql.TINYINT(unsigned=True), nullable=False, comment="1 ASR 2 translation 3 TTS"),
        sa.Column("status", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Provider enabled state"),
        sa.Column("priority", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("100"), comment="Lower route priority wins"),
        sa.Column("supported_locales_json", mysql.JSON(), nullable=True, comment="Supported target locales snapshot"),
        sa.Column("active_version_id", mysql.BIGINT(unsigned=True), nullable=True, comment="Logical active provider version id"), _created_at(), _updated_at(),
        sa.CheckConstraint("capability IN (1,2,3)", name="ck_provider_config_capability"),
        sa.CheckConstraint("status IN (1,2)", name="ck_provider_config_status"),
        comment="Logical AI provider routing configuration", **TABLE_OPTIONS,
    )
    op.create_index("uk_provider_config_public_id", "provider_config", ["public_id"], unique=True)
    op.create_index("uk_provider_config_code", "provider_config", ["provider_code"], unique=True)
    op.create_index("idx_provider_config_capability_status_priority", "provider_config", ["capability", "status", "priority"])

    op.create_table(
        "provider_version",
        _id(), _public_id(),
        sa.Column("provider_config_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical provider config id"),
        sa.Column("version_no", mysql.BIGINT(unsigned=True), nullable=False, comment="Monotonic provider version number"),
        sa.Column("model_name", mysql.VARCHAR(128), nullable=False, comment="Provider model identifier"),
        sa.Column("endpoint_url", mysql.VARCHAR(512), nullable=False, comment="Provider API endpoint"),
        sa.Column("timeout_ms", mysql.BIGINT(unsigned=True), nullable=False, comment="External request timeout in milliseconds"),
        sa.Column("config_json", mysql.JSON(), nullable=True, comment="Non-secret immutable provider options"),
        sa.Column("encrypted_secret", mysql.VARBINARY(4096), nullable=False, comment="Envelope encrypted provider credential"),
        sa.Column("encryption_key_id", mysql.VARCHAR(128), nullable=False, comment="Credential encryption key identifier"),
        sa.Column("status", mysql.TINYINT(unsigned=True), nullable=False, server_default=sa.text("1"), comment="Version enabled state"),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"), _created_at(),
        sa.CheckConstraint("status IN (1,2)", name="ck_provider_version_status"),
        comment="Immutable model endpoint and encrypted credential version", **TABLE_OPTIONS,
    )
    op.create_index("uk_provider_version_public_id", "provider_version", ["public_id"], unique=True)
    op.create_index("uk_provider_version_config_no", "provider_version", ["provider_config_id", "version_no"], unique=True)

    op.create_table(
        "provider_price",
        _id(), _public_id(),
        sa.Column("provider_version_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical immutable provider version id"),
        sa.Column("capability", mysql.TINYINT(unsigned=True), nullable=False, comment="Provider capability"),
        sa.Column("model_name", mysql.VARCHAR(128), nullable=False, comment="Priced provider model"),
        sa.Column("target_locale", mysql.VARCHAR(16), nullable=True, comment="Optional locale-specific price"),
        sa.Column("billing_unit", mysql.VARCHAR(32), nullable=False, comment="Unit such as characters or milliseconds"),
        sa.Column("unit_size", mysql.BIGINT(unsigned=True), nullable=False, comment="Quantity covered by one price unit"),
        sa.Column("unit_price_microunit", mysql.BIGINT(unsigned=True), nullable=False, comment="Price in micro currency units"),
        sa.Column("currency", mysql.CHAR(3), nullable=False, comment="ISO 4217 currency code"),
        sa.Column("effective_from", mysql.DATETIME(fsp=3), nullable=False, comment="UTC inclusive price effective time"),
        sa.Column("effective_to", mysql.DATETIME(fsp=3), nullable=True, comment="UTC exclusive price end time"),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical creator account id"), _created_at(),
        sa.CheckConstraint("capability IN (1,2,3)", name="ck_provider_price_capability"),
        sa.CheckConstraint("unit_price_microunit >= 0", name="ck_provider_price_unit_price"),
        sa.CheckConstraint("unit_size > 0", name="ck_provider_price_unit_size"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_provider_price_effective_range"),
        comment="Immutable provider price effective-dated records", **TABLE_OPTIONS,
    )
    op.create_index("uk_provider_price_public_id", "provider_price", ["public_id"], unique=True)
    op.create_index("idx_provider_price_lookup", "provider_price", ["provider_version_id", "capability", "model_name", "effective_from"])

    op.create_table(
        "ai_usage_record",
        _id(), _public_id(),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical project id"),
        sa.Column("task_id", mysql.BIGINT(unsigned=True), nullable=True, comment="Logical optional task id"),
        sa.Column("provider_version_id", mysql.BIGINT(unsigned=True), nullable=False, comment="Logical provider version id"),
        sa.Column("request_id", mysql.VARCHAR(128), nullable=False, comment="Idempotent external request identifier"),
        sa.Column("capability", mysql.TINYINT(unsigned=True), nullable=False, comment="Provider capability"),
        sa.Column("model_name", mysql.VARCHAR(128), nullable=False, comment="Provider model snapshot"),
        sa.Column("target_locale", mysql.VARCHAR(16), nullable=True, comment="Output locale when applicable"),
        sa.Column("input_units", mysql.BIGINT(unsigned=True), nullable=False, comment="Metered input quantity"),
        sa.Column("output_units", mysql.BIGINT(unsigned=True), nullable=False, comment="Metered output quantity"),
        sa.Column("duration_ms", mysql.BIGINT(unsigned=True), nullable=False, comment="Provider request duration in milliseconds"),
        sa.Column("status", mysql.TINYINT(unsigned=True), nullable=False, comment="Usage outcome status"),
        sa.Column("unit_price_microunit", mysql.BIGINT(unsigned=True), nullable=False, comment="Applied unit price snapshot"),
        sa.Column("cost_microunit", mysql.BIGINT(unsigned=True), nullable=False, comment="Calculated immutable cost"),
        sa.Column("price_snapshot_json", mysql.JSON(), nullable=False, comment="Applied immutable price rule snapshot"),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True, comment="Safe provider failure code"), _created_at(),
        sa.CheckConstraint("capability IN (1,2,3)", name="ck_ai_usage_record_capability"),
        sa.CheckConstraint("status IN (1,2,3)", name="ck_ai_usage_record_status"),
        sa.CheckConstraint("cost_microunit >= 0", name="ck_ai_usage_record_cost"),
        sa.CheckConstraint("input_units >= 0", name="ck_ai_usage_record_input_units"),
        sa.CheckConstraint("output_units >= 0", name="ck_ai_usage_record_output_units"),
        comment="Append-only metered AI provider request records", **TABLE_OPTIONS,
    )
    op.create_index("uk_ai_usage_record_public_id", "ai_usage_record", ["public_id"], unique=True)
    op.create_index("uk_ai_usage_record_request", "ai_usage_record", ["request_id"], unique=True)
    op.create_index("idx_ai_usage_project_created", "ai_usage_record", ["project_id", "created_at"])
    op.create_index("idx_ai_usage_provider_created", "ai_usage_record", ["provider_version_id", "created_at"])


def downgrade() -> None:
    for table_name in (
        "ai_usage_record", "provider_price", "provider_version", "provider_config",
        "task_event", "subtitle_segment", "source_segment", "media_asset",
        "translation_task", "translation_project",
    ):
        op.drop_table(table_name)
