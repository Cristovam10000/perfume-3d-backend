from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .core.exceptions import register_exception_handlers
from .core.logging import configure_logging, get_logger
from .database import SessionFactory, create_all, engine
from .modules.captures.processor import FakeProcessor
from .modules.captures.queue import ProcessingQueue
from .modules.captures.router import router as captures_router
from .modules.captures.service import CaptureService
from .modules.health.router import router as health_router
from .storage.local_storage import LocalStorage


@asynccontextmanager
async def production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap de produção: tabelas, storage, worker da fila."""
    configure_logging()
    log = get_logger("app.lifespan")

    await create_all()

    storage = LocalStorage()
    storage.ensure_dirs()

    processor = FakeProcessor()
    queue = ProcessingQueue()
    service = CaptureService(SessionFactory, storage, processor, queue)

    app.state.capture_service = service
    app.state.queue = queue

    queue.start(service.process_job)
    log.info("Backend pronto em %s:%s", settings.app_host, settings.app_port)

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

    return app


app = create_app()
