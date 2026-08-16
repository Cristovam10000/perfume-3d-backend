from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from ...core.exceptions import NotFoundError, ValidationError
from ...dependencies import get_capture_service
from .schemas import CaptureStatusResponse, CreateCaptureResponse
from .service import CaptureService, IncomingImage
from .transparency_classifier import MATERIAL_AUTO, VALID_MATERIALS
from .view_router import VALID_VIEW_LABELS

router = APIRouter(prefix="/captures", tags=["captures"])


@router.post(
    "",
    response_model=CreateCaptureResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_capture(
    images: list[UploadFile] = File(..., description="Lote de imagens (JPEG)"),
    views: list[str] = Form(
        default=[],
        description=(
            "Rótulos de vista paralelos a `images` (mesmo índice). Valores válidos: "
            "front, left, back, right, top, extra. Se omitido ou vazio, o backend "
            "usa CLIPViewRouter para decidir. `top` é opcional e não vai para o "
            "Hunyuan (que usa só as 4 cardeais) — alimenta a projeção da textura "
            "da tampa no pós-processamento."
        ),
    ),
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
    material: str | None = Form(
        default=None,
        description=(
            "Material do frasco: glass, opaque ou auto. Quando informado, decide "
            "diretamente se o refinador aplica vidro PBR ou preserva a textura. "
            "Omitido ou `auto` deixa a decisao com o ClipTransparencyClassifier."
        ),
    ),
    label_box: str | None = Form(
        default=None,
        alias="labelBox",
        description=(
            "Retangulo da label na foto **frontal**, como `x,y,w,h` normalizados "
            "em [0,1] relativos a foto inteira. Quando enviado, o backend pula o "
            "detector automatico e projeta exatamente essa regiao. Omitido, o "
            "HomographyLabelExtractor tenta achar sozinho e desiste em silencio "
            "se nao encontrar nada confiavel."
        ),
    ),
    service: CaptureService = Depends(get_capture_service),
) -> CreateCaptureResponse:
    """Recebe o lote de imagens e cria um job de reconstrucao 3D."""
    normalized_views: list[str | None] = _normalize_views(views, len(images))
    normalized_material = _normalize_material(material)
    normalized_label_box = _normalize_label_box(label_box)

    incoming = [
        IncomingImage(
            filename=f.filename or "image.jpg",
            content=await f.read(),
            view=normalized_views[i],
        )
        for i, f in enumerate(images)
    ]
    job_id = await service.create_job(
        incoming,
        product_id=product_id,
        material=normalized_material,
        label_box=normalized_label_box,
    )
    return CreateCaptureResponse(job_id=job_id)


def _normalize_views(views: list[str], image_count: int) -> list[str | None]:
    """Valida e normaliza a lista de views vinda do multipart.

    - Lista vazia => todos None (cliente legado, dispara CLIPViewRouter).
    - Lista com tamanho diferente de `image_count` => 422.
    - Valores fora de VALID_VIEW_LABELS => 422 (preserva contrato).
    - Case-insensitive: 'FRONT' vira 'front'.
    - Strings vazias viram None (cliente envia "" para extras sem rótulo).
    """
    if not views:
        return [None] * image_count

    if len(views) != image_count:
        raise ValidationError(
            f"Quantidade de views ({len(views)}) não bate com a de imagens "
            f"({image_count}); envie um view por imagem ou omita o campo."
        )

    normalized: list[str | None] = []
    for raw in views:
        cleaned = (raw or "").strip().lower()
        if cleaned == "":
            normalized.append(None)
            continue
        if cleaned not in VALID_VIEW_LABELS:
            raise ValidationError(
                f"View inválido: {raw!r}. Esperado um de: "
                f"{sorted(VALID_VIEW_LABELS)} ou vazio."
            )
        normalized.append(cleaned)
    return normalized


def _normalize_material(material: str | None) -> str | None:
    """Valida o material vindo do multipart.

    - Ausente, vazio ou `auto` => None (o pipeline decide pelo CLIP).
    - `glass` / `opaque` => valor normalizado em minusculas.
    - Qualquer outra coisa => 422.

    `auto` colapsa para None de proposito: os dois significam a mesma coisa
    para o pipeline, e guardar um so valor evita ter que tratar dois casos
    equivalentes em toda leitura do banco.
    """
    cleaned = (material or "").strip().lower()
    if cleaned in ("", MATERIAL_AUTO):
        return None
    if cleaned not in VALID_MATERIALS:
        raise ValidationError(
            f"Material inválido: {material!r}. Esperado um de: "
            f"{sorted(VALID_MATERIALS)}, 'auto' ou vazio."
        )
    return cleaned


# Menor lado aceito para a marcacao, em fracao da foto. Abaixo disso a regiao
# tem poucos pixels para virar textura e provavelmente foi toque acidental.
_LABEL_BOX_MIN_LADO = 0.02


def _normalize_label_box(label_box: str | None) -> str | None:
    """Valida `x,y,w,h` normalizados da marcacao manual da label.

    - Ausente ou vazio => None (cai no detector automatico).
    - Fora de [0,1], degenerado ou estourando a borda => 422.

    Devolve string porque e assim que fica no banco: a coluna guarda o que o
    app mandou, e quem converte para numeros e o pipeline. Reformatar aqui
    normaliza a representacao (sem espacos, 6 casas) sem perder precisao util.
    """
    cleaned = (label_box or "").strip()
    if not cleaned:
        return None

    partes = [p.strip() for p in cleaned.split(",")]
    if len(partes) != 4:
        raise ValidationError(
            f"labelBox inválido: {label_box!r}. Esperado 'x,y,w,h' normalizados."
        )
    try:
        x, y, w, h = (float(p) for p in partes)
    except ValueError:
        raise ValidationError(
            f"labelBox com valor não numérico: {label_box!r}."
        ) from None

    if not all(0.0 <= v <= 1.0 for v in (x, y, w, h)):
        raise ValidationError(
            f"labelBox fora de [0,1]: {label_box!r}."
        )
    if w < _LABEL_BOX_MIN_LADO or h < _LABEL_BOX_MIN_LADO:
        raise ValidationError(
            f"labelBox pequeno demais: {label_box!r}. "
            f"Largura e altura mínimas: {_LABEL_BOX_MIN_LADO}."
        )
    if x + w > 1.0 or y + h > 1.0:
        raise ValidationError(
            f"labelBox ultrapassa a borda da foto: {label_box!r}."
        )
    return f"{x:.6f},{y:.6f},{w:.6f},{h:.6f}"


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
        product_id=job.product_id,
        error=job.error,
    )
