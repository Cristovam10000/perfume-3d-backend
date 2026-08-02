"""IntegratedPipeline: compoe os stages do fluxo IA num Processor unico.

Sequencia executada por process(input):
    (1) ImagePreprocessor   -> fotos_clean/
    (2) BackgroundRemover   -> fotos_mask/
    (3) ImageEmbedder + ModelCache.lookup
            HIT  -> copia GLB cacheado -> output_path -> retorna
            MISS -> continua
    (4) Hunyuan3DProcessor  -> raw.glb
    (5) TransparencyClassifier -> body_mode (glass | keep | auto)
    (6) MeshRefiner         -> refined.glb (vidro PBR se transparente)
    (7) LabelExtractor + Upscaler + Projector
                            -> with_label.glb (degrade se nao achou label)
    (7.5) TopProjector      -> with_top.glb (so quando o app rotula uma foto
                               como `top`; o Hunyuan nao reconstroi o topo)
    (8) ModelCache.store    -> persiste em modelos_3d_universais + UPSERT
                               opcional em modelos_3d_produto

Falhas em stages opcionais sao logadas e o pipeline degrada (usa o GLB do
stage anterior). Falha do Hunyuan propaga ProcessingError.

A composicao concreta dos stages e responsabilidade do main.build_pipeline().
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ...core.logging import get_logger
from ...storage.local_storage import LocalStorage
from .background_remover import BackgroundRemover
from .cache import CacheHit, ModelCache
from .embeddings import ImageEmbedder
from .image_preprocessor import ImagePreprocessor
from .label_extractor import LabelExtractor
from .label_projector import (
    BlenderLabelProjector,
    LabelProjectionInput,
    LabelProjector,
)
from .label_upscaler import LabelUpscaler
from .mesh_refiner import MeshRefiner, RefinementInput
from .processor import (
    Hunyuan3DProcessor,
    Processor,
    ProcessingError,
    ProcessingInput,
    ProcessingResult,
)
from .top_projector import (
    DisabledTopProjector,
    TopProjectionInput,
    TopProjector,
)
from .transparency_classifier import (
    DisabledTransparencyClassifier,
    TransparencyClassifier,
)
from .view_router import TOP_VIEW, PositionalViewRouter, ViewRouter

_log = get_logger("captures.pipeline")


class IntegratedPipeline(Processor):
    """Pipeline composto: preprocess -> rembg -> cache -> Hunyuan -> pos-proc.

    Cada stage e injetado como ABC. Substituicoes (bypass `Disabled*`) ficam
    transparentes — o pipeline so confia nas interfaces.
    """

    def __init__(
        self,
        preprocessor: ImagePreprocessor,
        background_remover: BackgroundRemover,
        embedder: ImageEmbedder,
        cache: ModelCache,
        hunyuan: Hunyuan3DProcessor,
        mesh_refiner: MeshRefiner,
        label_extractor: LabelExtractor,
        label_upscaler: LabelUpscaler,
        label_projector: LabelProjector,
        storage: LocalStorage,
        *,
        view_router: ViewRouter | None = None,
        transparency_classifier: TransparencyClassifier | None = None,
        top_projector: TopProjector | None = None,
        front_axis: str = "front_y_neg",
        top_cosine_threshold: float = 0.45,
        label_min_confidence: float = 0.3,
        label_target_size: int = 2048,
    ):
        self.preprocessor = preprocessor
        self.background_remover = background_remover
        self.embedder = embedder
        self.cache = cache
        self.hunyuan = hunyuan
        self.mesh_refiner = mesh_refiner
        self.label_extractor = label_extractor
        self.label_upscaler = label_upscaler
        self.label_projector = label_projector
        self.storage = storage
        self.view_router = view_router or PositionalViewRouter()
        self.transparency_classifier = (
            transparency_classifier or DisabledTransparencyClassifier()
        )
        self.top_projector = top_projector or DisabledTopProjector()
        self.front_axis = front_axis
        self.top_cosine_threshold = top_cosine_threshold
        self.label_min_confidence = label_min_confidence
        self.label_target_size = label_target_size

    # ----------------------------------------------------------------- public

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        workspace = self._workspace(input.job_id)
        workspace.mkdir(parents=True, exist_ok=True)

        preprocessed = await self._safe_preprocess(input.image_paths, workspace)
        masked = await self._safe_segment(preprocessed, workspace)

        # (3) cache lookup
        hit = await self._safe_lookup(preprocessed)
        if hit is not None:
            return await self._serve_cache_hit(hit, input)

        # (3.5) view router — reordena masked para [front, left, back, right, *extras]
        # antes do Hunyuan. Os hints vêm de `input.views` (app guiado); se vazios,
        # o CLIPViewRouter decide. PositionalViewRouter mantém comportamento legado.
        routing = await self._safe_route_views(masked, input.views)
        ordered_for_hunyuan = routing.ordered
        _log.info(
            "View router (%s) reordenou %d imagens para o Hunyuan",
            routing.source,
            len(ordered_for_hunyuan),
        )

        # (4) Hunyuan ou fallback
        raw_glb = workspace / "raw.glb"
        try:
            await self.hunyuan.process(
                ProcessingInput(
                    job_id=input.job_id,
                    image_paths=ordered_for_hunyuan,
                    output_path=raw_glb,
                )
            )
        except Exception as exc:
            _log.exception("Hunyuan falhou para job %s: %s", input.job_id, exc)
            raise ProcessingError(f"Hunyuan falhou: {exc}") from exc

        # (5) transparencia: decide o body_mode do refiner pelas fotos
        body_mode = await self._safe_classify_transparency(preprocessed)
        # (6) mesh refiner
        refined = await self._safe_refine(raw_glb, input, workspace, body_mode)
        # (7) label extract + upscale + project
        com_label = await self._safe_apply_label(
            refined,
            preprocessed,
            masked,
            workspace,
        )
        # (7.5) textura do topo — só quando o app rotulou uma foto como `top`
        final_glb = await self._safe_apply_top(
            com_label,
            routing.assignments.get(TOP_VIEW),
            workspace,
        )

        # Copia para o output_path real do job (em storage/models/<job>.glb).
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_glb, input.output_path)

        # (8) cache store
        try:
            embedding = await self.embedder.embed(preprocessed)
            await self.cache.store(
                embedding,
                final_glb,
                source_job_id=input.job_id,
                product_id=input.product_id,
                liquid_color=input.liquid_color,
            )
        except Exception as exc:
            _log.warning(
                "Falha ao persistir cache para job %s: %s",
                input.job_id,
                exc,
            )

        n = len(masked) or len(input.image_paths)
        return ProcessingResult(
            output_path=input.output_path,
            message=f"Modelo gerado via Hunyuan3D-2mv a partir de {n} imagem(ns)",
            origem="generated",
        )

    # -------------------------------------------------------------- internals

    def _workspace(self, job_id: str) -> Path:
        return self.storage.root / "tmp" / "pipeline" / job_id

    async def _safe_preprocess(
        self, fotos: list[Path], workspace: Path
    ) -> list[Path]:
        destino = workspace / "preprocessed"
        destino.mkdir(parents=True, exist_ok=True)
        saidas: list[Path] = []
        for indice, foto in enumerate(fotos, start=1):
            saida = destino / f"{indice:02d}_{foto.stem}.jpg"
            try:
                await self.preprocessor.preprocess(foto, saida)
                saidas.append(saida)
            except Exception as exc:
                _log.warning(
                    "Preprocess falhou em %s (%s); usando foto original",
                    foto,
                    exc,
                )
                saidas.append(foto)
        return saidas

    async def _safe_segment(
        self, fotos: list[Path], workspace: Path
    ) -> list[Path]:
        destino = workspace / "masked"
        destino.mkdir(parents=True, exist_ok=True)
        saidas: list[Path] = []
        for indice, foto in enumerate(fotos, start=1):
            saida = destino / f"{indice:02d}_{foto.stem}.png"
            try:
                await self.background_remover.remove(foto, saida)
                saidas.append(saida)
            except Exception as exc:
                _log.warning(
                    "Background remover falhou em %s (%s); enviando foto preprocessada",
                    foto,
                    exc,
                )
                saidas.append(foto)
        return saidas

    async def _safe_lookup(self, fotos: list[Path]) -> CacheHit | None:
        try:
            embedding = await self.embedder.embed(fotos)
            return await self.cache.lookup(embedding)
        except Exception as exc:
            _log.warning("Cache lookup falhou (%s); tratando como miss", exc)
            return None

    async def _safe_route_views(
        self,
        masked: list[Path],
        hints: list[str | None] | None,
    ):
        """Roteia vistas com tolerância a falhas — sempre devolve algo utilizável.

        Falha no router (ex: CLIP estourou) cai para PositionalViewRouter
        para preservar o comportamento legado em vez de matar o job.
        """
        try:
            return await self.view_router.route(masked, hints=hints)
        except Exception as exc:
            _log.warning(
                "ViewRouter falhou (%s); usando ordem original do upload",
                exc,
            )
            return await PositionalViewRouter().route(masked)

    async def _serve_cache_hit(
        self, hit: CacheHit, input: ProcessingInput
    ) -> ProcessingResult:
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(hit.glb_path, input.output_path)
        except Exception as exc:
            _log.error(
                "GLB cacheado %s sumiu do disco para job %s (%s); regerando",
                hit.glb_path,
                input.job_id,
                exc,
            )
            raise ProcessingError(
                f"Cache hit em {hit.universal_id} mas GLB inacessivel: {exc}"
            ) from exc

        # Em cache hit, ainda atualizamos o vinculo produto -> molde se vier
        # product_id na request. Permite que tenants diferentes amarrem o mesmo
        # molde universal aos seus respectivos produtos sem duplicar a entrada
        # no cache global.
        if input.product_id is not None:
            await self.cache.bind_product(
                hit.universal_id,
                product_id=input.product_id,
                capture_job_id=input.job_id,
            )

        return ProcessingResult(
            output_path=input.output_path,
            message=(
                f"Modelo entregue pelo cache (similaridade={hit.similarity:.3f}, "
                f"hits={hit.hit_count})"
            ),
            origem="cache",
            similarity=hit.similarity,
        )

    async def _safe_classify_transparency(self, fotos: list[Path]) -> str:
        """Traduz o veredito de transparencia para o body_mode do refiner.

        True -> "glass" (aplica vidro), False -> "keep" (preserva textura),
        None/falha -> "auto" (heuristica legada do script Blender).
        """
        try:
            resultado = await self.transparency_classifier.classify(fotos)
        except Exception as exc:
            _log.warning(
                "Classificador de transparencia falhou (%s); usando body_mode=auto",
                exc,
            )
            return "auto"

        if resultado.transparent is None:
            return "auto"
        body_mode = "glass" if resultado.transparent else "keep"
        _log.info(
            "Transparencia (%s): %s -> body_mode=%s (conf=%.3f)",
            resultado.source,
            "transparente" if resultado.transparent else "opaco",
            body_mode,
            resultado.confidence,
        )
        return body_mode

    async def _safe_refine(
        self,
        cleaned: Path,
        input: ProcessingInput,
        workspace: Path,
        body_mode: str = "auto",
    ) -> Path:
        refined = workspace / "refined.glb"
        try:
            await self.mesh_refiner.refine(
                RefinementInput(
                    input_glb=cleaned,
                    output_glb=refined,
                    liquid_color=input.liquid_color,
                    body_mode=body_mode,
                )
            )
            return refined
        except Exception as exc:
            _log.warning(
                "Mesh refiner falhou (%s); seguindo com cleaned.glb",
                exc,
            )
            return cleaned

    async def _safe_apply_label(
        self,
        refined: Path,
        preprocessed: list[Path],
        masked: list[Path],
        workspace: Path,
    ) -> Path:
        with_label = workspace / "with_label.glb"
        label_raw = workspace / "label_raw.png"
        label_upscaled = workspace / "label_upscaled.png"

        # Extrai a melhor label entre todas as fotos disponiveis.
        melhor_label: Path | None = None
        melhor_conf = 0.0
        melhor_altura: float | None = None
        for foto, mascara in zip(preprocessed, masked):
            try:
                extraida = await self.label_extractor.extract(
                    foto,
                    mascara,
                    label_raw,
                )
            except Exception as exc:
                _log.warning(
                    "Label extractor falhou em %s (%s); proximo",
                    foto,
                    exc,
                )
                continue
            if extraida is None:
                continue
            if extraida.confidence > melhor_conf:
                melhor_conf = extraida.confidence
                melhor_label = extraida.image_path
                # A altura vem da mesma foto da label — o projetor a usa para
                # posicionar o decal na altura certa do frasco.
                melhor_altura = extraida.vertical_position
                if extraida.confidence >= self.label_min_confidence:
                    # Acima do threshold; usa essa e para de procurar.
                    break

        if melhor_label is None or melhor_conf < self.label_min_confidence:
            _log.info(
                "Sem label confiavel (melhor=%.3f, threshold=%.3f); refined.glb e o final",
                melhor_conf,
                self.label_min_confidence,
            )
            return refined

        # Upscale + projetar.
        try:
            await self.label_upscaler.upscale(
                melhor_label,
                label_upscaled,
                self.label_target_size,
            )
        except Exception as exc:
            _log.warning("Label upscale falhou (%s); seguindo sem label", exc)
            return refined

        try:
            # Usa BlenderLabelProjector quando disponivel; outras impls seguem
            # o mesmo contrato.
            await self.label_projector.project(
                LabelProjectionInput(
                    input_glb=refined,
                    label_image=label_upscaled,
                    output_glb=with_label,
                    front_axis=self.front_axis,
                    vertical_position=melhor_altura,
                )
            )
            return with_label
        except Exception as exc:
            _log.warning(
                "Label projector falhou (%s); refined.glb e o final",
                exc,
            )
            return refined

    async def _safe_apply_top(
        self,
        entrada: Path,
        foto_topo: Path | None,
        workspace: Path,
    ) -> Path:
        """Cola a foto do topo na tampa. No-op quando nao ha foto rotulada.

        O Hunyuan nao reconstroi o topo do frasco — as 4 vistas cardeais nao o
        enxergam, e ele entrega um disco liso sem textura. Este stage so roda
        quando o app marca uma foto como `top` no `POST /captures`; sem isso,
        `routing.assignments` nao traz a chave e o GLB anterior passa direto.
        """
        if foto_topo is None:
            _log.info("Sem foto de topo rotulada; pulando projecao da tampa")
            return entrada

        with_top = workspace / "with_top.glb"
        try:
            await self.top_projector.project(
                TopProjectionInput(
                    input_glb=entrada,
                    top_image=foto_topo,
                    output_glb=with_top,
                    cosine_threshold=self.top_cosine_threshold,
                )
            )
            _log.info("Textura do topo aplicada a partir de %s", foto_topo.name)
            return with_top
        except Exception as exc:
            _log.warning(
                "Top projector falhou (%s); seguindo com o GLB anterior",
                exc,
            )
            return entrada


# ruff/pyright nao usa BlenderLabelProjector na ABC, mas o import esta acima
# para que a doc citacao seja navegavel; suprimimos a marcacao.
_ = BlenderLabelProjector
