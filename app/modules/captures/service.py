from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from ...core.exceptions import ValidationError
from ...storage.local_storage import LocalStorage
from .models import CaptureJob
from .processor import Processor, ProcessingInput
from .queue import ProcessingQueue
from .repository import CaptureRepository
from .status import CaptureStatus


@dataclass(frozen=True)
class IncomingImage:
    filename: str
    content: bytes


class CaptureService:
    """Orquestra as use cases do módulo captures.

    Mantém a camada HTTP (router) magra: receber/validar input, chamar service,
    traduzir resultado. Toda a coreografia (criar job → salvar imagens → filar
    processamento → atualizar status) vive aqui.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: LocalStorage,
        processor: Processor,
        queue: ProcessingQueue,
    ):
        self._session_factory = session_factory
        self._storage = storage
        self._processor = processor
        self._queue = queue

    # ------------------------------------------------------------------ HTTP

    async def create_job(self, images: list[IncomingImage]) -> str:
        """Cria job, persiste imagens em disco + DB, e enfileira processamento."""
        if not images:
            raise ValidationError("Nenhuma imagem recebida")

        job_id = str(uuid4())
        saved_paths: list[tuple[str, Path]] = []

        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            await repo.create_job(job_id)

            for image in images:
                path = self._storage.save_upload(job_id, image.filename, image.content)
                saved_paths.append((image.filename, path))
                await repo.add_image(job_id, image.filename, str(path))

            await session.commit()

        await self._queue.submit(job_id)
        return job_id

    async def get_job(self, job_id: str) -> CaptureJob | None:
        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            return await repo.get(job_id)

    # ---------------------------------------------------------------- WORKER

    async def process_job(self, job_id: str) -> None:
        """Executa um job completo. Registrado como handler da fila no bootstrap."""
        image_paths, output_path = await self._prepare_job(job_id)
        if image_paths is None:
            return  # job sumiu entre o submit e o pop — tolerante.

        try:
            result = await self._processor.process(
                ProcessingInput(
                    job_id=job_id,
                    image_paths=image_paths,
                    output_path=output_path,
                )
            )
        except Exception as exc:
            await self._mark_error(job_id, str(exc))
            raise

        await self._mark_completed(job_id, result.message)

    async def _prepare_job(
        self, job_id: str
    ) -> tuple[list[Path], Path] | tuple[None, None]:
        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            job = await repo.get(job_id)
            if job is None:
                return (None, None)

            image_paths = [Path(img.path) for img in job.images]
            output_path = self._storage.model_path(job_id)

            await repo.update_status(
                job_id,
                CaptureStatus.PROCESSING,
                message="Reconstruindo modelo 3D",
            )
            await session.commit()

        return image_paths, output_path

    async def _mark_completed(self, job_id: str, message: str) -> None:
        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            await repo.update_status(
                job_id,
                CaptureStatus.COMPLETED,
                message=message,
                model_path=self._storage.model_public_path(job_id),
            )
            await session.commit()

    async def _mark_error(self, job_id: str, error: str) -> None:
        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            await repo.update_status(
                job_id,
                CaptureStatus.ERROR,
                message="Falha no processamento",
                error=error,
            )
            await session.commit()
