from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.imagegen.model import ImageGenerationJob, ImageJobStatus


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class ImageGenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        account_id: int,
        prompt: str,
        size: str,
        count: int,
        reference_count: int,
    ) -> ImageGenerationJob:
        job = ImageGenerationJob(
            public_id=str(ULID()),
            account_id=account_id,
            prompt=prompt,
            size=size,
            count=count,
            reference_count=reference_count,
            status=int(ImageJobStatus.RUNNING),
            error_code=None,
            error_message=None,
            created_at=_now(),
            finished_at=None,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, public_id: str) -> ImageGenerationJob | None:
        return (
            await self.session.execute(
                select(ImageGenerationJob).where(
                    ImageGenerationJob.public_id == public_id
                )
            )
        ).scalar_one_or_none()

    async def list_page(
        self, account_id: int, *, limit: int, offset: int
    ) -> list[ImageGenerationJob]:
        result = await self.session.execute(
            select(ImageGenerationJob)
            .where(ImageGenerationJob.account_id == account_id)
            .order_by(ImageGenerationJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def list_all(self, *, limit: int, offset: int) -> list[ImageGenerationJob]:
        result = await self.session.execute(
            select(ImageGenerationJob)
            .order_by(ImageGenerationJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def mark_succeeded(self, job: ImageGenerationJob) -> None:
        job.status = int(ImageJobStatus.SUCCEEDED)
        job.finished_at = _now()
        await self.session.flush()

    async def mark_failed(
        self, job: ImageGenerationJob, *, error_code: str, error_message: str
    ) -> None:
        job.status = int(ImageJobStatus.FAILED)
        job.error_code = error_code
        job.error_message = error_message
        job.finished_at = _now()
        await self.session.flush()
