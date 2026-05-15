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
from app.main import (
    build_classifier,
    build_color_detector,
    build_processor,
    create_app,
)
from app.modules.captures.classifier import CLIPClassifier, DisabledClassifier
from app.modules.captures.color_detector import (
    AverageColorDetector,
    DisabledColorDetector,
)
from app.modules.captures.processor import (
    FakeProcessor,
    TemplateFittingProcessor,
    TemplateProcessor,
)
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


class TestAppStructure:
    def test_create_app_without_lifespan_boots(self, tmp_path: Path):
        app = create_app(storage_dir=tmp_path / "s", lifespan=None)
        routes = {getattr(r, "path", None) for r in app.routes}
        assert "/health" in routes
        assert "/captures" in routes
        assert "/captures/{job_id}/status" in routes
        # StaticFiles aparece como Mount em /files.
        assert any(getattr(r, "path", "").startswith("/files") for r in app.routes)


class TestBuildProcessorFactory:
    def test_returns_fake_when_type_is_fake(self, tmp_path: Path):
        cfg = Settings(processor_type="fake", storage_root=tmp_path)
        processor = build_processor(cfg)
        assert isinstance(processor, FakeProcessor)

    def test_returns_template_when_type_is_template(self, tmp_path: Path):
        cfg = Settings(
            processor_type="template",
            storage_root=tmp_path,
            blender_executable=tmp_path / "blender.exe",
            templates_dir=tmp_path / "templates",
        )
        processor = build_processor(cfg)
        assert isinstance(processor, TemplateProcessor)
        # Settings sao propagadas para o processor
        assert processor.blender_executable == cfg.blender_executable
        assert processor.templates_dir == cfg.templates_dir

    def test_returns_template_fitting_when_type_is_template_fitting(
        self, tmp_path: Path
    ):
        cfg = Settings(
            processor_type="template_fitting",
            storage_root=tmp_path,
            blender_executable=tmp_path / "blender.exe",
            templates_dir=tmp_path / "templates",
            default_template_id="cylindrical_basic",
            template_fitting_prefer_classifier=True,
        )
        processor = build_processor(cfg)
        assert isinstance(processor, TemplateFittingProcessor)
        assert processor.blender_executable == cfg.blender_executable
        assert processor.templates_dir == cfg.templates_dir
        assert processor.default_template_id == "cylindrical_basic"
        assert processor.prefer_input_template_id is True

    def test_invalid_processor_type_rejected_by_pydantic(self, tmp_path: Path):
        # Literal no Settings barra valores invalidos antes
        # de chegar no factory. Garantia da camada de config, nao do main.
        with pytest.raises(Exception):  # pydantic.ValidationError
            Settings(processor_type="meshroom", storage_root=tmp_path)


class TestBuildClassifierFactory:
    def test_returns_disabled_with_default_template_id(self, tmp_path: Path):
        cfg = Settings(
            classifier_type="disabled",
            default_template_id="my_default",
            storage_root=tmp_path,
        )
        classifier = build_classifier(cfg)
        assert isinstance(classifier, DisabledClassifier)
        assert classifier.default_template_id == "my_default"

    def test_clip_with_no_normalized_templates_raises(self, tmp_path: Path):
        empty_dir = tmp_path / "templates"
        empty_dir.mkdir()
        cfg = Settings(
            classifier_type="clip",
            templates_dir=empty_dir,
            storage_root=tmp_path,
        )
        with pytest.raises(ValueError, match="Nenhum template GLB"):
            build_classifier(cfg)

    def test_clip_filters_to_existing_templates(self, tmp_path: Path):
        # Cria apenas rectangular_basic.glb — outros templates do catalog ficam fora.
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "rectangular_basic.glb").write_bytes(b"glTF\x02fake")

        cfg = Settings(
            classifier_type="clip",
            templates_dir=templates_dir,
            storage_root=tmp_path,
        )
        classifier = build_classifier(cfg)
        assert isinstance(classifier, CLIPClassifier)
        # Apenas o template existente entrou no mapping.
        assert set(classifier.templates.keys()) == {"rectangular_basic"}

    def test_invalid_classifier_type_rejected_by_pydantic(self, tmp_path: Path):
        with pytest.raises(Exception):
            Settings(classifier_type="resnet", storage_root=tmp_path)


class TestBuildColorDetectorFactory:
    def test_returns_disabled_when_type_is_disabled(self, tmp_path: Path):
        cfg = Settings(color_detector_type="disabled", storage_root=tmp_path)
        detector = build_color_detector(cfg)
        assert isinstance(detector, DisabledColorDetector)

    def test_returns_average_when_type_is_average(self, tmp_path: Path):
        cfg = Settings(color_detector_type="average", storage_root=tmp_path)
        detector = build_color_detector(cfg)
        assert isinstance(detector, AverageColorDetector)

    def test_invalid_color_detector_type_rejected_by_pydantic(self, tmp_path: Path):
        with pytest.raises(Exception):
            Settings(color_detector_type="histogram", storage_root=tmp_path)
