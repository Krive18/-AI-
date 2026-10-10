"""End-to-end hybrid smoke: youdao text interpretation + TTS + render.

Creates a synthetic youdao-mode project/task in the local database pointing at
an existing extracted source.wav, runs TranslationWorker._run_task through the
new hybrid path (interpret_text -> standard synthesize -> render), prints the
resulting segments, assets and usage records, then cleans up.
"""

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as redis_lib
from sqlalchemy import delete, select
from ulid import ULID

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.modules.cost.model import AiUsageRecord
from app.modules.media.model import MediaAsset, SourceSegment, SubtitleSegment, TaskEvent
from app.modules.media.storage import LocalObjectStorage
from app.modules.media_runtime.ffmpeg import FFmpeg
from app.modules.project.schemas import TranslationMode
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory
from app.modules.translation.model import (
    TaskStage,
    TaskStatus,
    TranslationProject,
    TranslationTask,
)
from app.workers.pipeline import TranslationWorker

BACKEND_DIR = Path(__file__).resolve().parent
PRIVATE = BACKEND_DIR / ".ai_translation_private"
DONOR_WAV = PRIVATE / "projects" / "01M1JDBTWP8ZKKD4B0E41SEXMK" / "shared" / "source.wav"


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


async def main() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env")
    db = DatabaseManager(settings)
    cipher = ProviderSecretCipher(
        settings.provider_secret_encryption_key.get_secret_value()
    )
    storage = LocalObjectStorage(PRIVATE)
    probe = FFmpeg().probe(DONOR_WAV)

    async with db.session_factory() as session:
        account_id = await session.scalar(select(TranslationProject.created_by))
        if account_id is None:
            raise RuntimeError("no existing project to borrow an account id from")

    public_id = str(ULID())
    shared_dir = PRIVATE / "projects" / public_id / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    source_wav = shared_dir / "source.wav"
    shutil.copyfile(DONOR_WAV, source_wav)
    object_key = f"projects/{public_id}/shared/source.wav"

    async with db.session_factory() as session:
        now = _now()
        project = TranslationProject(
            public_id=public_id,
            created_by=account_id,
            name="智能翻译混合联调",
            source_filename="hybrid-smoke.mp4",
            source_content_type="video/mp4",
            source_object_key=object_key,
            source_sha256=None,
            source_size_bytes=source_wav.stat().st_size,
            source_duration_ms=probe.duration_ms,
            source_container=probe.container,
            source_video_codec=probe.video_codec,
            source_audio_codec=probe.audio_codec,
            translation_mode=TranslationMode.YOUDAO.value,
            status=6,  # ProjectStatus.PROCESSING
            progress_percent=45,
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        await session.flush()
        session.add(
            MediaAsset(
                public_id=str(ULID()),
                project_id=project.id,
                task_id=None,
                asset_type=2,  # AssetType.EXTRACTED_AUDIO
                object_key=object_key,
                content_type="audio/wav",
                sha256=None,
                size_bytes=source_wav.stat().st_size,
                duration_ms=None,
                container="wav",
                video_codec=None,
                audio_codec="pcm_s16le",
                metadata_json=None,
                created_at=now,
            )
        )
        task = TranslationTask(
            public_id=str(ULID()),
            project_id=project.id,
            target_locale="vi-VN",
            # Terminal status keeps a live local worker from racing this
            # synthetic task; the stage methods below don't read it.
            status=int(TaskStatus.SUCCEEDED),
            stage=int(TaskStage.TRANSLATING),
            progress_percent=0,
            voice_id=None,
            retry_count=0,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        await session.commit()
        project_id = project.id
        task_id = task.id
        print(f"created youdao-mode project id={project_id} task id={task_id}")

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
        # Render needs a real video source; validate interpret -> segments
        # -> standard TTS -> dubbed.wav, which is the new hybrid wiring.
        await worker._translate_with_youdao(task_id)
        await worker._synthesize(task_id)
    finally:
        await redis.aclose()

    async with db.session_factory() as session:
        task = await session.get(TranslationTask, task_id)
        print(f"\ntask status={task.status} stage={task.stage} progress={task.progress_percent}")
        sources = list(
            (
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.project_id == project_id)
                    .order_by(SourceSegment.sequence_no)
                )
            ).all()
        )
        subtitles = list(
            (
                await session.scalars(
                    select(SubtitleSegment).where(SubtitleSegment.task_id == task_id)
                )
            ).all()
        )
        print(f"=== {len(sources)} SourceSegment / {len(subtitles)} SubtitleSegment ===")
        for source, subtitle in zip(sources, subtitles, strict=False):
            print(
                f"#{source.sequence_no} [{source.start_ms}-{source.end_ms}ms] "
                f"{source.source_text} -> {subtitle.translated_text}"
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
            print(
                f"{event.event_type} stage={event.stage} progress={event.progress_percent}"
            )
        usage = list(
            (
                await session.scalars(
                    select(AiUsageRecord).where(
                        AiUsageRecord.project_id == project_id
                    )
                )
            ).all()
        )
        print("\n=== AiUsageRecord ===")
        for record in usage:
            print(
                f"capability={record.capability} request={record.request_id} "
                f"input_units={record.input_units} status={record.status} cost={record.cost_microunit}"
            )
        assets = list(
            (
                await session.scalars(
                    select(MediaAsset).where(MediaAsset.project_id == project_id)
                )
            ).all()
        )
        print("\n=== MediaAsset ===")
        for asset in assets:
            print(f"type={asset.asset_type} key={asset.object_key} size={asset.size_bytes}")

        await session.execute(
            delete(AiUsageRecord).where(AiUsageRecord.project_id == project_id)
        )
        await session.execute(
            delete(TaskEvent).where(TaskEvent.project_id == project_id)
        )
        await session.execute(delete(SubtitleSegment).where(SubtitleSegment.task_id == task_id))
        await session.execute(
            delete(SourceSegment).where(SourceSegment.project_id == project_id)
        )
        await session.execute(delete(MediaAsset).where(MediaAsset.project_id == project_id))
        await session.execute(
            delete(TranslationTask).where(TranslationTask.project_id == project_id)
        )
        await session.execute(
            delete(TranslationProject).where(TranslationProject.id == project_id)
        )
        await session.commit()
    shutil.rmtree(PRIVATE / "projects" / public_id, ignore_errors=True)
    print("\ncleanup done")


if __name__ == "__main__":
    asyncio.run(main())
