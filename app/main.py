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
from .modules.captures.classifier import (
    Classifier,
    CLIPClassifier,
    DisabledClassifier,
)
from .modules.captures.color_detector import (
    AverageColorDetector,
    ColorDetector,
    DisabledColorDetector,
)
from .modules.captures.processor import (
    FakeProcessor,
    Processor,
    TemplateProcessor,
)
from .modules.captures.queue import ProcessingQueue
from .modules.captures.router import router as captures_router
from .modules.captures.service import CaptureService
from .modules.captures.templates_catalog import TEMPLATE_DESCRIPTIONS
from .modules.health.router import router as health_router
from .storage.local_storage import LocalStorage


def build_processor(config: Settings = settings) -> Processor:
    """Factory que materializa o Processor conforme `PROCESSOR_TYPE` do `.env`.

    Centraliza o conhecimento de "qual processor usar" num só lugar — o resto
    do sistema continua programando contra a ABC `Processor`.
    """
    if config.processor_type == "fake":
        return FakeProcessor()
    if config.processor_type == "template":
        return TemplateProcessor(
            blender_executable=config.blender_executable,
            templates_dir=config.templates_dir,
        )
    # Pydantic Literal já barra valores fora desses dois antes daqui chegar,
    # mas mantemos a guarda explícita para o caso de a Settings ser construída
    # programaticamente em algum teste.
    raise ValueError(f"processor_type inválido: {config.processor_type!r}")


def build_classifier(config: Settings = settings) -> Classifier:
    """Factory do Classifier conforme `CLASSIFIER_TYPE` do `.env`.

    Para o modo `clip`, filtra `TEMPLATE_DESCRIPTIONS` mantendo apenas os
    templates que de fato têm GLB normalizado em disco — assim o CLIP nunca
    devolve um `template_id` que o `TemplateProcessor` não consegue usar.
    """
    if config.classifier_type == "disabled":
        return DisabledClassifier(default_template_id=config.default_template_id)

    if config.classifier_type == "clip":
        available = {
            tid: desc
            for tid, desc in TEMPLATE_DESCRIPTIONS.items()
            if (config.templates_dir / f"{tid}.glb").exists()
        }
        if not available:
            raise ValueError(
                f"Nenhum template GLB normalizado em {config.templates_dir} — "
                "rode os scripts de normalização antes de ativar CLASSIFIER_TYPE=clip."
            )
        return CLIPClassifier(
            model_name=config.clip_model,
            templates=available,
        )

    raise ValueError(f"classifier_type inválido: {config.classifier_type!r}")


def build_color_detector(config: Settings = settings) -> ColorDetector:
    """Factory do detector de cor conforme `COLOR_DETECTOR_TYPE` do `.env`."""
    if config.color_detector_type == "disabled":
        return DisabledColorDetector()
    if config.color_detector_type == "average":
        return AverageColorDetector()
    raise ValueError(
        f"color_detector_type inválido: {config.color_detector_type!r}"
    )


@asynccontextmanager
async def production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap de produção: tabelas, storage, worker da fila."""
    configure_logging()
    log = get_logger("app.lifespan")

    await create_all()

    storage = LocalStorage()
    storage.ensure_dirs()

    processor = build_processor()
    classifier = build_classifier()
    color_detector = build_color_detector()
    queue = ProcessingQueue()
    service = CaptureService(
        SessionFactory,
        storage,
        processor,
        queue,
        classifier=classifier,
        color_detector=color_detector,
    )

    app.state.capture_service = service
    app.state.queue = queue

    queue.start(service.process_job)
    log.info(
        "Backend pronto em %s:%s (processor=%s, classifier=%s, color=%s)",
        settings.app_host,
        settings.app_port,
        settings.processor_type,
        settings.classifier_type,
        settings.color_detector_type,
    )

    try:
        yield
    finally:
        await queue.stop()
        await engine.dispose()


def create_app(
    *,
    storage_dir: Path | None = None,
    lifespan=production_lifespan,
) -> FastAPI:
    """Factory da aplicação FastAPI.

    Parametrizado para permitir montar uma app de teste sem Postgres/worker:
    basta passar `storage_dir=<tmp>` e `lifespan=None`, populando o
    `app.state.capture_service` manualmente.
    """
    static_root = Path(storage_dir or settings.storage_root)
    (static_root / "uploads").mkdir(parents=True, exist_ok=True)
    (static_root / "models").mkdir(parents=True, exist_ok=True)

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

    app.mount(
        "/files",
        StaticFiles(directory=static_root),
        name="files",
    )

    # Templates normalizados expostos para o viewer local poder visualizar
    # cada template "puro" (sem customização do líquido/label do job). Útil
    # pra inspecionar a saída do `generate_*_template.py` sem precisar
    # disparar uma captura nova pelo app.
    if settings.templates_dir.exists():
        app.mount(
            "/templates",
            StaticFiles(directory=settings.templates_dir),
            name="templates",
        )

    return app


app = create_app()
