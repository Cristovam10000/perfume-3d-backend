from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...core.exceptions import ValidationError
from ...core.logging import get_logger
from ...storage.local_storage import LocalStorage
from .models import CaptureJob
from .processor import Processor, ProcessingInput
from .queue import ProcessingQueue
from .repository import CaptureRepository
from .status import CaptureStatus

_log = get_logger("captures.service")


@dataclass(frozen=True)
class _JobPreparado:
    """Dados do job lidos do banco antes de chamar o Processor.

    Era uma tupla; virou dataclass ao ganhar o quinto campo, quando o
    desempacotamento posicional deixou de ser legivel.
    """

    image_paths: list[Path]
    output_path: Path
    product_id: int | None
    views: list[str | None]
    material: str | None
    label_box: str | None


@dataclass(frozen=True)
class IncomingImage:
    filename: str
    content: bytes
    # Rótulo opcional da vista enviada pelo app guiado.
    # Valores válidos: front/left/back/right/extra (case-insensitive).
    # None = cliente legado; CLIPViewRouter decide no pipeline.
    view: str | None = None


class CaptureService:
    """Orquestra as use cases do modulo captures.

    Camada HTTP (router) fica magra: receber/validar input, chamar service,
    traduzir resultado. A geracao 3D em si e responsabilidade do `Processor`
    injetado (FakeProcessor, TemplateProcessor ou IntegratedPipeline).
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

    async def create_job(
        self,
        images: list[IncomingImage],
        *,
        product_id: int | None = None,
        material: str | None = None,
        label_box: str | None = None,
    ) -> str:
        """Cria job, persiste imagens em disco + DB, e enfileira processamento."""
        if not images:
            raise ValidationError("Nenhuma imagem recebida")

        job_id = str(uuid4())

        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            await repo.create_job(
                job_id,
                product_id=product_id,
                material=material,
                label_box=label_box,
            )

            for image in images:
                path = self._storage.save_upload(job_id, image.filename, image.content)
                await repo.add_image(
                    job_id,
                    image.filename,
                    str(path),
                    view=image.view,
                )

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
        prep = await self._prepare_job(job_id)
        if prep is None:
            return  # job sumiu entre o submit e o pop — tolerante.

        try:
            result = await self._processor.process(
                ProcessingInput(
                    job_id=job_id,
                    image_paths=prep.image_paths,
                    output_path=prep.output_path,
                    product_id=prep.product_id,
                    views=prep.views,
                    material=prep.material,
                    label_box=prep.label_box,
                )
            )
        except Exception as exc:
            await self._mark_error(job_id, str(exc))
            raise

        await self._mark_completed(
            job_id,
            result.message,
            prep.product_id,
            tem_preview=result.preview_path is not None,
        )

    async def _prepare_job(self, job_id: str) -> _JobPreparado | None:
        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            job = await repo.get(job_id)
            if job is None:
                return None

            preparado = _JobPreparado(
                image_paths=[Path(img.path) for img in job.images],
                output_path=self._storage.model_path(job_id),
                product_id=job.product_id,
                views=[img.view for img in job.images],
                material=job.material,
                label_box=job.label_box,
            )

            await repo.update_status(
                job_id,
                CaptureStatus.PROCESSING,
                message="Reconstruindo modelo 3D",
            )
            await session.commit()

        return preparado

    async def _mark_completed(
        self,
        job_id: str,
        message: str,
        product_id: int | None = None,
        *,
        tem_preview: bool = False,
    ) -> None:
        model_public_path = self._storage.model_public_path(job_id)
        preview_public_path = (
            self._storage.preview_public_path(job_id) if tem_preview else None
        )

        # O vinculo vai em transacao propria, antes do status. Se ele falhar
        # (produto apagado no meio do job, por exemplo) o GLB continua valido e
        # o job precisa concluir mesmo assim — o que nao pode e a falha sumir:
        # ela entra na `message`, que o app mostra.
        aviso: str | None = None
        if product_id is not None:
            try:
                async with self._session_factory() as session:
                    repo = CaptureRepository(session)
                    await repo.vincular_produto(
                        product_id=product_id,
                        job_id=job_id,
                        model_public_path=model_public_path,
                        preview_public_path=preview_public_path,
                    )
                    await session.commit()
            except Exception as exc:
                aviso = f"modelo gerado, mas nao vinculado ao produto: {exc}"
                _log.warning(
                    "Falha ao vincular job %s ao produto %s: %s",
                    job_id,
                    product_id,
                    exc,
                )

        async with self._session_factory() as session:
            repo = CaptureRepository(session)
            await repo.update_status(
                job_id,
                CaptureStatus.COMPLETED,
                message=f"{message} — {aviso}" if aviso else message,
                model_path=model_public_path,
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
