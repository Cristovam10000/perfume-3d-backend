from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CaptureImage, CaptureJob
from .status import CaptureStatus


class CaptureRepository:
    """Acesso a dados dos jobs de captura. Mantém as queries em um só lugar."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(
        self,
        job_id: str,
        *,
        product_id: int | None = None,
        material: str | None = None,
    ) -> CaptureJob:
        job = CaptureJob(
            id=job_id,
            status=CaptureStatus.WAITING.value,
            message="Aguardando processamento",
            product_id=product_id,
            material=material,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def add_image(
        self,
        job_id: str,
        filename: str,
        path: str,
        *,
        view: str | None = None,
    ) -> CaptureImage:
        image = CaptureImage(
            job_id=job_id,
            filename=filename,
            path=path,
            view=view,
        )
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

    async def vincular_produto(
        self,
        *,
        product_id: int,
        job_id: str,
        model_public_path: str,
    ) -> None:
        """Faz o produto comercial apontar para o GLB recem-gerado.

        Este vinculo morava dentro de `ModelCache.store()`. Ficava refem do
        `CACHE_ENABLED`: com o cache desligado o job concluia, o GLB ia para o
        disco, mas `modelos_3d_produto` continuava vazia e o app mostrava o
        placeholder para sempre. Persistir o modelo do produto nao e trabalho
        do cache — e por isso mora aqui, no unico ponto por onde todo job
        concluido passa (cache hit, cache miss e cache desligado).

        Grava `model_public_path` (`/files/models/<job>.glb`), nao o caminho de
        disco: a coluna e servida direto ao app, que a resolve como URL. Vale
        tambem em cache hit, porque o pipeline sempre copia o GLB final para
        `storage/models/<job>.glb` antes de concluir.

        `modelo_universal_id` fica de fora do UPDATE de proposito: quem cuida
        dessa coluna e o cache, e este metodo roda depois dele.
        """
        await self.session.execute(
            text(
                "INSERT INTO modelos_3d_produto ("
                "  produto_id, caminho_arquivo_modelo, status, "
                "  capture_job_id, criado_em, atualizado_em"
                ") VALUES ("
                "  :produto_id, :path, 'completo', "
                "  :job_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                ") "
                "ON CONFLICT (produto_id) DO UPDATE SET "
                "  caminho_arquivo_modelo = EXCLUDED.caminho_arquivo_modelo, "
                "  capture_job_id = EXCLUDED.capture_job_id, "
                "  status = 'completo', "
                "  atualizado_em = CURRENT_TIMESTAMP"
            ),
            {
                "produto_id": product_id,
                "path": model_public_path,
                "job_id": job_id,
            },
        )
        # Flag denormalizada lida pela listagem de estoque (`possui_modelo_3d`).
        # Sem ela o card do produto nao sabe que ganhou um modelo.
        await self.session.execute(
            text("UPDATE produtos SET possui_modelo_3d = true WHERE id = :id"),
            {"id": product_id},
        )
