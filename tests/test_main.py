"""Smoke tests da app completa.

Monta `create_app()` com `lifespan=None` e faz o setup manual (equivalente
ao que o `production_lifespan` faz), para exercitar o fluxo ponta a ponta
sem Postgres e sem sofrer com o ASGITransport do httpx (que ignora lifespan).
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.main import build_pipeline, create_app
from app.modules.captures.pipeline import IntegratedPipeline
from app.modules.captures.processor import FakeProcessor, TemplateProcessor
from app.modules.captures.queue import ProcessingQueue
from app.modules.captures.service import CaptureService
from app.storage.local_storage import LocalStorage


@pytest_asyncio.fixture
async def integration_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """App completa com DB SQLite + worker real + FakeProcessor sem delay."""
    storage_root = tmp_path / "storage"
    db_path = tmp_path / "app.db"

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )

    app = create_app(storage_dir=storage_root, lifespan=None)

    storage = LocalStorage(root=storage_root)
    storage.ensure_dirs()
    queue = ProcessingQueue()
    service = CaptureService(
        session_factory,
        storage,
        FakeProcessor(simulated_duration=0.0),
        queue,
    )
    app.state.capture_service = service
    app.state.queue = queue
    queue.start(service.process_job)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client
    finally:
        await queue.stop()
        await engine.dispose()


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, integration_client: AsyncClient):
        response = await integration_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEndToEndFlow:
    @pytest.mark.asyncio
    async def test_upload_process_and_serve_glb(
        self, integration_client: AsyncClient, tmp_path: Path
    ):
        # 1. Upload de 2 imagens.
        files = [
            ("images", ("a.jpg", b"\xff\xd8\xff\x00aaa", "image/jpeg")),
            ("images", ("b.jpg", b"\xff\xd8\xff\x00bbb", "image/jpeg")),
        ]
        create = await integration_client.post("/captures", files=files)
        assert create.status_code == 201
        job_id = create.json()["jobId"]

        # 2. Aguarda worker processar o job (FakeProcessor é instantâneo).
        app = integration_client._transport.app  # type: ignore[attr-defined]
        await app.state.queue.join()

        # 3. Status deve estar completed com modelUrl absoluto.
        status = await integration_client.get(f"/captures/{job_id}/status")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert body["modelUrl"] == f"http://testserver/files/models/{job_id}.glb"
        assert body["error"] is None

        # 4. Static files serve o .glb gerado com header glTF válido.
        glb = await integration_client.get(body["modelUrl"])
        assert glb.status_code == 200
        assert glb.content[:4] == b"glTF", "Deveria servir um GLB válido"

    @pytest.mark.asyncio
    async def test_upload_with_product_id_is_accepted(
        self, integration_client: AsyncClient
    ):
        """productId opcional no form-data nao deve quebrar o upload."""
        files = [
            ("images", ("a.jpg", b"\xff\xd8\xff\x00aaa", "image/jpeg")),
        ]
        data = {"productId": "42"}
        create = await integration_client.post("/captures", files=files, data=data)
        assert create.status_code == 201

        job_id = create.json()["jobId"]
        app = integration_client._transport.app  # type: ignore[attr-defined]
        await app.state.queue.join()

        status = await integration_client.get(f"/captures/{job_id}/status")
        assert status.status_code == 200
        assert status.json()["status"] == "completed"


class TestAppStructure:
    def test_create_app_without_lifespan_boots(self, tmp_path: Path):
        app = create_app(storage_dir=tmp_path / "s", lifespan=None)
        routes = {getattr(r, "path", None) for r in app.routes}
        assert "/health" in routes
        assert "/captures" in routes
        assert "/captures/{job_id}/status" in routes
        # StaticFiles aparece como Mount em /files.
        assert any(getattr(r, "path", "").startswith("/files") for r in app.routes)


class TestBuildPipelineFactory:
    def test_fake_pipeline_returns_fake_processor(self, tmp_path: Path):
        cfg = Settings(pipeline_mode="fake", storage_root=tmp_path)
        processor = build_pipeline(cfg, LocalStorage(root=tmp_path))
        assert isinstance(processor, FakeProcessor)

    def test_template_pipeline_returns_template_processor(self, tmp_path: Path):
        cfg = Settings(
            pipeline_mode="template",
            storage_root=tmp_path,
            blender_executable=tmp_path / "blender.exe",
            templates_dir=tmp_path / "templates",
        )
        processor = build_pipeline(cfg, LocalStorage(root=tmp_path))
        assert isinstance(processor, TemplateProcessor)
        assert processor.blender_executable == cfg.blender_executable
        assert processor.templates_dir == cfg.templates_dir

    def test_integrated_pipeline_compose_stages(self, tmp_path: Path):
        cfg = Settings(
            pipeline_mode="integrated",
            cache_enabled=False,
            pipeline_fallback_to_template=False,
            storage_root=tmp_path,
            blender_executable=tmp_path / "blender.exe",
            templates_dir=tmp_path / "templates",
        )
        processor = build_pipeline(cfg, LocalStorage(root=tmp_path))
        assert isinstance(processor, IntegratedPipeline)
        # Sem cache, embedder e cache caem para Disabled.
        from app.modules.captures.cache import DisabledModelCache
        from app.modules.captures.embeddings import DisabledEmbedder

        assert isinstance(processor.embedder, DisabledEmbedder)
        assert isinstance(processor.cache, DisabledModelCache)
        assert processor.fallback_processor is None

    def test_integrated_with_fallback_template(self, tmp_path: Path):
        cfg = Settings(
            pipeline_mode="integrated",
            pipeline_fallback_to_template=True,
            cache_enabled=False,
            storage_root=tmp_path,
            blender_executable=tmp_path / "blender.exe",
            templates_dir=tmp_path / "templates",
        )
        processor = build_pipeline(cfg, LocalStorage(root=tmp_path))
        assert isinstance(processor, IntegratedPipeline)
        assert isinstance(processor.fallback_processor, TemplateProcessor)

    def test_invalid_pipeline_mode_rejected_by_pydantic(self, tmp_path: Path):
        # Literal["fake","template","integrated"] no Settings barra valores invalidos.
        with pytest.raises(Exception):  # pydantic.ValidationError
            Settings(pipeline_mode="meshroom", storage_root=tmp_path)

    def test_legacy_processor_type_template_fitting_falls_back_to_integrated(
        self, tmp_path: Path, caplog
    ):
        """O .env antigo tinha PROCESSOR_TYPE=template_fitting (invalido).

        O alias legacy deve manter PIPELINE_MODE=integrated com warning.
        """
        import logging

        from app.config import _apply_legacy_aliases

        cfg = Settings(
            processor_type="template_fitting",
            pipeline_mode="integrated",
            storage_root=tmp_path,
        )
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _apply_legacy_aliases(cfg)
        assert cfg.pipeline_mode == "integrated"
        assert any("template_fitting" in rec.message for rec in caplog.records)

    def test_legacy_processor_type_fake_is_applied(self, tmp_path: Path):
        from app.config import _apply_legacy_aliases

        cfg = Settings(
            processor_type="fake",
            pipeline_mode="integrated",
            storage_root=tmp_path,
        )
        _apply_legacy_aliases(cfg)
        assert cfg.pipeline_mode == "fake"
