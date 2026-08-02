from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings, settings
from .core.exceptions import register_exception_handlers
from .core.logging import configure_logging, get_logger
from .database import SessionFactory, create_all, engine
from .modules.captures.background_remover import (
    BackgroundRemover,
    DisabledBackgroundRemover,
    RembgBackgroundRemover,
)
from .modules.captures.cache import (
    ClipSimilarityCache,
    DisabledModelCache,
    ModelCache,
)
from .modules.captures.embeddings import (
    ClipImageEmbedder,
    DisabledEmbedder,
    ImageEmbedder,
)
from .modules.captures.image_preprocessor import (
    DisabledImagePreprocessor,
    ImagePreprocessor,
    StandardImagePreprocessor,
)
from .modules.captures.label_extractor import (
    DisabledLabelExtractor,
    HomographyLabelExtractor,
    LabelExtractor,
)
from .modules.captures.label_projector import (
    BlenderLabelProjector,
    DisabledLabelProjector,
    LabelProjector,
)
from .modules.captures.top_projector import (
    BlenderTopProjector,
    DisabledTopProjector,
    TopProjector,
)
from .modules.captures.label_upscaler import (
    DisabledLabelUpscaler,
    LabelUpscaler,
    LanczosLabelUpscaler,
)
from .modules.captures.mesh_refiner import (
    BlenderMeshRefiner,
    DisabledMeshRefiner,
    MeshRefiner,
)
from .modules.captures.modelos_universais import ensure_captures_schema
from .modules.captures.pipeline import IntegratedPipeline
from .modules.captures.processor import (
    FakeProcessor,
    Hunyuan3DProcessor,
    Processor,
)
from .modules.captures.queue import ProcessingQueue
from .modules.captures.transparency_classifier import (
    ClipTransparencyClassifier,
    DisabledTransparencyClassifier,
    TransparencyClassifier,
)
from .modules.captures.router import router as captures_router
from .modules.captures.service import CaptureService
from .modules.captures.view_router import (
    CLIPViewRouter,
    LabeledViewRouter,
    PositionalViewRouter,
    ViewRouter,
)
from .modules.health.router import router as health_router
from .modules.sales.repository import ensure_sales_schema
from .modules.sales.router import router as sales_router
from .storage.local_storage import LocalStorage


# --------------------------------------------------------------- stage builders


def build_image_preprocessor(config: Settings = settings) -> ImagePreprocessor:
    if config.image_preprocessor_type == "disabled":
        return DisabledImagePreprocessor()
    return StandardImagePreprocessor()


def build_background_remover(config: Settings = settings) -> BackgroundRemover:
    if config.background_remover_type == "disabled":
        return DisabledBackgroundRemover()
    return RembgBackgroundRemover(model_name=config.background_remover_model)


def build_mesh_refiner(config: Settings = settings) -> MeshRefiner:
    if config.mesh_refiner_type == "disabled":
        return DisabledMeshRefiner()
    return BlenderMeshRefiner(blender_executable=config.blender_executable)


def build_transparency_classifier(
    config: Settings = settings,
) -> TransparencyClassifier:
    if config.transparency_classifier_type == "disabled":
        return DisabledTransparencyClassifier()
    return ClipTransparencyClassifier(
        model_name=config.cache_embedding_model,
        threshold=config.transparency_threshold,
    )


def build_label_extractor(config: Settings = settings) -> LabelExtractor:
    if config.label_extractor_type == "disabled":
        return DisabledLabelExtractor()
    return HomographyLabelExtractor()


def build_label_upscaler(config: Settings = settings) -> LabelUpscaler:
    if config.label_upscaler_type == "disabled":
        return DisabledLabelUpscaler()
    return LanczosLabelUpscaler(target_size=config.label_target_size)


def build_label_projector(config: Settings = settings) -> LabelProjector:
    if config.label_projector_type == "disabled":
        return DisabledLabelProjector()
    return BlenderLabelProjector(blender_executable=config.blender_executable)


def build_top_projector(config: Settings = settings) -> TopProjector:
    if config.top_projector_type == "disabled":
        return DisabledTopProjector()
    return BlenderTopProjector(blender_executable=config.blender_executable)


def build_embedder(config: Settings = settings) -> ImageEmbedder:
    if not config.cache_enabled or config.cache_embedder_type == "disabled":
        return DisabledEmbedder()
    return ClipImageEmbedder(model_name=config.cache_embedding_model)


def build_model_cache(
    config: Settings = settings, storage: LocalStorage | None = None
) -> ModelCache:
    if not config.cache_enabled:
        return DisabledModelCache()
    return ClipSimilarityCache(
        session_factory=SessionFactory,
        storage=storage or LocalStorage(),
        similarity_threshold=config.cache_similarity_threshold,
    )


def build_view_router(config: Settings = settings) -> ViewRouter:
    """Cria o ViewRouter conforme `VIEW_ROUTER_TYPE`.

    Sempre embrulhamos no LabeledViewRouter: se o cliente enviar `views`
    no upload, ele usa esses labels diretamente; se não, delega para o
    router configurado (CLIP ou positional).
    """
    if config.view_router_type == "positional":
        fallback: ViewRouter = PositionalViewRouter()
    else:
        fallback = CLIPViewRouter(
            model_name=config.cache_embedding_model,
            fallback=PositionalViewRouter(),
        )
    return LabeledViewRouter(fallback=fallback)


def build_hunyuan(config: Settings = settings) -> Hunyuan3DProcessor:
    return Hunyuan3DProcessor(
        service_url=config.hunyuan_url,
        timeout_seconds=config.hunyuan_timeout_seconds,
        octree_resolution=config.hunyuan_octree_resolution,
        num_inference_steps=config.hunyuan_num_inference_steps,
        guidance_scale=config.hunyuan_guidance_scale,
        mc_algo=config.hunyuan_mc_algo,
        texture_resolution=config.hunyuan_texture_resolution,
    )


# --------------------------------------------------------------- root factory


def build_pipeline(
    config: Settings = settings,
    storage: LocalStorage | None = None,
) -> Processor:
    """Materializa o `Processor` raiz conforme `PIPELINE_MODE`.

    `fake`       -> FakeProcessor (sintetico, sem deps)
    `integrated` -> IntegratedPipeline (preprocess + rembg + cache CLIP + Hunyuan + pos-proc)
    """
    storage = storage or LocalStorage()

    if config.pipeline_mode == "fake":
        return FakeProcessor()

    return IntegratedPipeline(
        preprocessor=build_image_preprocessor(config),
        background_remover=build_background_remover(config),
        embedder=build_embedder(config),
        cache=build_model_cache(config, storage),
        hunyuan=build_hunyuan(config),
        mesh_refiner=build_mesh_refiner(config),
        label_extractor=build_label_extractor(config),
        label_upscaler=build_label_upscaler(config),
        label_projector=build_label_projector(config),
        storage=storage,
        view_router=build_view_router(config),
        transparency_classifier=build_transparency_classifier(config),
        top_projector=build_top_projector(config),
        front_axis=config.label_front_axis,
        top_cosine_threshold=config.top_cosine_threshold,
        label_min_confidence=config.label_min_confidence,
        label_target_size=config.label_target_size,
    )


# ------------------------------------------------------------------- lifespan


@asynccontextmanager
async def production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap de producao: tabelas, storage, worker da fila."""
    configure_logging()
    log = get_logger("app.lifespan")

    await create_all()
    await ensure_sales_schema(engine)
    await ensure_captures_schema(engine)

    storage = LocalStorage()
    storage.ensure_dirs()

    pipeline = build_pipeline(settings, storage)
    queue = ProcessingQueue()
    service = CaptureService(SessionFactory, storage, pipeline, queue)

    app.state.capture_service = service
    app.state.queue = queue

    queue.start(service.process_job)
    log.info(
        "Backend pronto em %s:%s (pipeline=%s, cache_enabled=%s, hunyuan_url=%s)",
        settings.app_host,
        settings.app_port,
        settings.pipeline_mode,
        settings.cache_enabled,
        settings.hunyuan_url,
    )

    try:
        yield
    finally:
        await queue.stop()
        await engine.dispose()


# ------------------------------------------------------------------- app


def create_app(
    *,
    storage_dir: Path | None = None,
    lifespan=production_lifespan,
) -> FastAPI:
    """Factory da aplicacao FastAPI.

    Parametrizado para permitir montar uma app de teste sem Postgres/worker:
    basta passar `storage_dir=<tmp>` e `lifespan=None`, populando o
    `app.state.capture_service` manualmente.
    """
    static_root = Path(storage_dir or settings.storage_root)
    (static_root / "uploads").mkdir(parents=True, exist_ok=True)
    (static_root / "models").mkdir(parents=True, exist_ok=True)
    (static_root / "cache").mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(captures_router)
    app.include_router(sales_router)

    app.mount(
        "/files",
        StaticFiles(directory=static_root),
        name="files",
    )

    return app


app = create_app()
