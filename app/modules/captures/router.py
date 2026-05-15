from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from ...core.exceptions import NotFoundError
from ...dependencies import get_capture_service
from .schemas import CaptureStatusResponse, CreateCaptureResponse
from .service import CaptureService, IncomingImage

router = APIRouter(prefix="/captures", tags=["captures"])


@router.post(
    "",
    response_model=CreateCaptureResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_capture(
    images: list[UploadFile] = File(..., description="Lote de imagens (JPEG)"),
    product_id: int | None = Form(
        default=None,
        alias="productId",
        description=(
            "ID do produto comercial (em /sales) ao qual a captura pertence. "
            "Quando enviado, o backend amarra o GLB ao produto via "
            "modelos_3d_produto ao final do pipeline. Quando omitido, o cache "
            "global ainda funciona; apenas o vinculo com produto fica vazio."
        ),
    ),
    service: CaptureService = Depends(get_capture_service),
) -> CreateCaptureResponse:
    """Recebe o lote de imagens e cria um job de reconstrucao 3D."""
    incoming = [
        IncomingImage(
            filename=f.filename or "image.jpg",
            content=await f.read(),
        )
        for f in images
    ]
    job_id = await service.create_job(incoming, product_id=product_id)
    return CreateCaptureResponse(job_id=job_id)


@router.get(
    "/{job_id}/status",
    response_model=CaptureStatusResponse,
    response_model_by_alias=True,
)
async def get_status(
    job_id: str,
    request: Request,
    service: CaptureService = Depends(get_capture_service),
) -> CaptureStatusResponse:
    """Informa o estado atual do job e, se concluído, a URL absoluta do modelo."""
    job = await service.get_job(job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} não encontrado")

    model_url: str | None = None
    if job.model_path:
        base = str(request.base_url).rstrip("/")
        model_url = f"{base}{job.model_path}"

    return CaptureStatusResponse(
        status=job.status,
        message=job.message,
        model_url=model_url,
        error=job.error,
    )
