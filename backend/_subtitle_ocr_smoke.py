"""Real OCR smoke test: insert ark_vision provider, run the pipeline OCR step.

Creates (or reuses) an enabled ark_vision provider that shares the local ark
provider credential, wires a real TranslationWorker against the local DB,
and runs _extract_subtitles_via_ocr for a synthetic subtitle-mode project
whose source video lives under the worktree private storage root.
"""

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as redis_lib
from sqlalchemy import delete, select
from ulid import ULID

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.modules.cost.model import AiUsageRecord
from app.modules.media.model import SourceSegment, TaskEvent
from app.modules.media.storage import LocalObjectStorage
from app.modules.media_runtime.ffmpeg import FFmpeg
from app.modules.project.schemas import TranslationMode
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory
from app.modules.translation.model import ProjectStatus, TranslationProject
from app.workers.pipeline import TranslationWorker

BACKEND_DIR = Path(__file__).resolve().parent
VIDEO = Path(os.environ["TEMP"]) / "ocr_smoke_source.mp4"
# The local ark key only has this model enabled; it accepts image inputs.
MODEL = "doubao-seed-2-0-lite-260428"
ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


async def ensure_ark_vision_provider(db: DatabaseManager, cipher: ProviderSecretCipher) -> None:
    async with db.session_factory() as session:
        existing = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.provider_code == "ark_vision")
        )
        if existing is not None:
            version = await session.get(ProviderVersion, existing.active_version_id)
            if version is not None and version.model_name != MODEL:
                version.model_name = MODEL
                await session.commit()
                print(f"ark_vision provider id={existing.id}: model set to {MODEL}")
            else:
                print(f"ark_vision provider already exists: id={existing.id}")
            return
        row = (
            await session.execute(
                select(ProviderConfig, ProviderVersion)
                .join(
                    ProviderVersion,
                    ProviderVersion.id == ProviderConfig.active_version_id,
                )
                .where(ProviderConfig.provider_code == "ark")
            )
        ).one()
        ark_config, ark_version = row
        secret = cipher.decrypt(ark_version.encrypted_secret)
        now = _now()
        config = ProviderConfig(
            public_id=str(ULID()),
            provider_code="ark_vision",
            display_name="豆包视觉字幕识别",
            capability=int(ProviderCapability.SUBTITLE_OCR),
            status=int(ProviderStatus.ENABLED),
            priority=100,
            supported_locales_json=None,
            active_version_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(config)
        await session.flush()
        version = ProviderVersion(
            public_id=str(ULID()),
            provider_config_id=config.id,
            version_no=1,
            model_name=MODEL,
            endpoint_url=ENDPOINT,
            timeout_ms=60_000,
            config_json=None,
            encrypted_secret=cipher.encrypt(secret),
            encryption_key_id="local-dev-key",
            status=int(ProviderStatus.ENABLED),
            created_by=1,
            created_at=now,
        )
        session.add(version)
        await session.flush()
        config.active_version_id = version.id
        await session.commit()
        print(f"created ark_vision provider id={config.id} reusing ark key")


async def main() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env")
    db = DatabaseManager(settings)
    cipher = ProviderSecretCipher(
        settings.provider_secret_encryption_key.get_secret_value()
    )
    await ensure_ark_vision_provider(db, cipher)

    storage = LocalObjectStorage(BACKEND_DIR / ".ai_translation_private")
    probe = FFmpeg().probe(VIDEO)

    project_id: int | None = None
    async with db.session_factory() as session:
        account_id = await session.scalar(select(TranslationProject.created_by))
        if account_id is None:
            raise RuntimeError("no existing project to borrow an account id from")
        public_id = str(ULID())
        object_key = f"projects/{public_id}/shared/source.mp4"
        target = storage.put_file(object_key, VIDEO)
        now = _now()
        project = TranslationProject(
            public_id=public_id,
            created_by=account_id,
            name="OCR联调测试",
            source_filename="source.mp4",
            source_content_type="video/mp4",
            source_object_key=object_key,
            source_sha256=None,
            source_size_bytes=target.stat().st_size,
            source_duration_ms=probe.duration_ms,
            source_container=probe.container,
            source_video_codec=probe.video_codec,
            source_audio_codec=probe.audio_codec,
            translation_mode=TranslationMode.SUBTITLE_OCR.value,
            status=int(ProjectStatus.RECOGNIZING),
            progress_percent=30,
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        await session.commit()
        project_id = project.id
        print(f"created subtitle-mode project id={project_id}")

    redis = redis_lib.from_url(settings.redis_url, protocol=settings.redis_protocol)
    worker = TranslationWorker(
        db.session_factory,
        redis,
        storage,
        FFmpeg(),
        ProviderRuntimeFactory(cipher),
        max_concurrency=1,
    )
    try:
        async with db.session_factory() as session:
            project = await session.get(TranslationProject, project_id)
            assert project is not None
            await worker._extract_subtitles_via_ocr(project.id, project.public_id)
    finally:
        await redis.aclose()

    async with db.session_factory() as session:
        segments = list(
            (
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.project_id == project_id)
                    .order_by(SourceSegment.sequence_no)
                )
            ).all()
        )
        print("\n=== SourceSegment ===")
        for segment in segments:
            print(
                f"#{segment.sequence_no} [{segment.start_ms//1000}s-{segment.end_ms//1000}s] {segment.source_text}"
            )
        events = list(
            (
                await session.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.project_id == project_id)
                    .order_by(TaskEvent.id)
                )
            ).all()
        )
        print("\n=== TaskEvent ===")
        for event in events:
            print(f"{event.event_type} stage={event.stage} progress={event.progress_percent}")
        usage = list(
            (
                await session.scalars(
                    select(AiUsageRecord).where(
                        AiUsageRecord.project_id == project_id,
                        AiUsageRecord.capability == int(ProviderCapability.SUBTITLE_OCR),
                    )
                )
            ).all()
        )
        print(f"\n=== AiUsageRecord capability=6: {len(usage)} records ===")
        for record in usage[:5]:
            print(
                f"request={record.request_id} input_units={record.input_units} status={record.status} cost={record.cost_microunit}"
            )
        project = await session.get(TranslationProject, project_id)
        print(f"\nproject status={project.status} progress={project.progress_percent}")

        await session.execute(
            delete(AiUsageRecord).where(AiUsageRecord.project_id == project_id)
        )
        await session.execute(
            delete(TaskEvent).where(TaskEvent.project_id == project_id)
        )
        await session.execute(
            delete(SourceSegment).where(SourceSegment.project_id == project_id)
        )
        await session.execute(
            delete(TranslationProject).where(TranslationProject.id == project_id)
        )
        await session.commit()
    storage.delete(object_key)
    print("\ncleanup done; ark_vision provider left configured")


if __name__ == "__main__":
    asyncio.run(main())
