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

from app.database import Base
from app.main import create_app
from app.modules.captures.processor import FakeProcessor
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
