from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CaptureImage, CaptureJob
from .status import CaptureStatus


class CaptureRepository:
    """Acesso a dados dos jobs de captura. Mantém as queries em um só lugar."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(self, job_id: str) -> CaptureJob:
        job = CaptureJob(
            id=job_id,
            status=CaptureStatus.WAITING.value,
            message="Aguardando processamento",
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def add_image(self, job_id: str, filename: str, path: str) -> CaptureImage:
        image = CaptureImage(job_id=job_id, filename=filename, path=path)
        self.session.add(image)
        await self.session.flush()
        return image

    async def get(self, job_id: str) -> CaptureJob | None:
        result = await self.session.execute(
            select(CaptureJob).where(CaptureJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: str,
        status: CaptureStatus,
        *,
        message: str | None = None,
        model_path: str | None = None,
        error: str | None = None,
    ) -> CaptureJob | None:
        job = await self.get(job_id)
        if job is None:
            return None
        job.status = status.value
        if message is not None:
            job.message = message
        if model_path is not None:
            job.model_path = model_path
        if error is not None:
            job.error = error
        await self.session.flush()
        return job
