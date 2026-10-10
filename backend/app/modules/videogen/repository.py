from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.videogen.model import VideoGenerationJob, VideoJobStatus


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class VideoGenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        account_id: int,
        prompt: str,
        size: str,
        duration_seconds: int,
        tier: int,
        reference_object_key: str | None = None,
    ) -> VideoGenerationJob:
        job = VideoGenerationJob(
            public_id=str(ULID()),
            account_id=account_id,
            prompt=prompt,
            size=size,
            duration_seconds=duration_seconds,
            tier=tier,
            reference_object_key=reference_object_key,
            status=int(VideoJobStatus.RUNNING),
            error_code=None,
            error_message=None,
            created_at=_now(),
            finished_at=None,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, public_id: str) -> VideoGenerationJob | None:
        return (
            await self.session.execute(
                select(VideoGenerationJob).where(
                    VideoGenerationJob.public_id == public_id
                )
            )
        ).scalar_one_or_none()

    async def list_page(
        self, account_id: int, *, limit: int, offset: int
    ) -> list[VideoGenerationJob]:
        result = await self.session.execute(
            select(VideoGenerationJob)
            .where(VideoGenerationJob.account_id == account_id)
            .order_by(VideoGenerationJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def list_all(self, *, limit: int, offset: int) -> list[VideoGenerationJob]:
        result = await self.session.execute(
            select(VideoGenerationJob)
            .order_by(VideoGenerationJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def mark_succeeded(self, job: VideoGenerationJob) -> None:
        job.status = int(VideoJobStatus.SUCCEEDED)
        job.finished_at = _now()
        await self.session.flush()

    async def mark_failed(
        self, job: VideoGenerationJob, *, error_code: str, error_message: str
    ) -> None:
        job.status = int(VideoJobStatus.FAILED)
        job.error_code = error_code
        job.error_message = error_message
        job.finished_at = _now()
        await self.session.flush()
