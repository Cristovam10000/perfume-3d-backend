from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import register_exception_handlers
from app.modules.captures.processor import (
    ProcessingInput,
    ProcessingResult,
    Processor,
)
from app.modules.captures.router import router as captures_router
from app.modules.captures.service import CaptureService
from app.modules.captures.status import CaptureStatus
from app.storage.local_storage import LocalStorage


class _RecordingProcessor(Processor):
    async def process(self, input: ProcessingInput) -> ProcessingResult:
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(b"fake-glb")
        return ProcessingResult(output_path=input.output_path, message="ok")


class _StubQueue:
    def __init__(self):
        self.submitted: list[str] = []

    async def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


@dataclass
class _Harness:
    app: FastAPI
    client: AsyncClient
    service: CaptureService
    queue: _StubQueue
    storage: LocalStorage


@pytest_asyncio.fixture
async def harness(session_factory, tmp_path: Path) -> AsyncIterator[_Harness]:
    storage = LocalStorage(root=tmp_path / "storage")
    storage.ensure_dirs()
    processor = _RecordingProcessor()
    queue = _StubQueue()
    service = CaptureService(session_factory, storage, processor, queue)  # type: ignore[arg-type]

    app = FastAPI()
    app.state.capture_service = service
    register_exception_handlers(app)
    app.include_router(captures_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield _Harness(app=app, client=client, service=service, queue=queue, storage=storage)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


class TestCreateCaptureEndpoint:
    @pytest.mark.asyncio
    async def test_accepts_images_and_returns_job_id(self, harness: _Harness):
        files = [
            ("images", ("001.jpg", b"\xff\xd8\xff\x00img1", "image/jpeg")),
            ("images", ("002.jpg", b"\xff\xd8\xff\x00img2", "image/jpeg")),
        ]
        response = await harness.client.post("/captures", files=files)

        assert response.status_code == 201
        body = response.json()
        assert "jobId" in body, "Resposta deve usar camelCase (jobId)"
        assert _is_uuid(body["jobId"])
        assert harness.queue.submitted == [body["jobId"]]

    @pytest.mark.asyncio
    async def test_rejects_request_without_images_field(self, harness: _Harness):
        response = await harness.client.post("/captures")
        # FastAPI valida o campo obrigatório antes de chegar no service.
        assert response.status_code == 422


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_job_returns_404(self, harness: _Harness):
        response = await harness.client.get("/captures/does-not-exist/status")
        assert response.status_code == 404
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_initial_status_is_waiting_with_null_model_url(
        self, harness: _Harness
    ):
        files = [("images", ("001.jpg", b"img", "image/jpeg"))]
        job_id = (await harness.client.post("/captures", files=files)).json()["jobId"]

        response = await harness.client.get(f"/captures/{job_id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == CaptureStatus.WAITING.value
        assert body["modelUrl"] is None
        assert body["error"] is None
        assert isinstance(body["message"], str)

    @pytest.mark.asyncio
    async def test_completed_job_returns_absolute_model_url(self, harness: _Harness):
        files = [("images", ("001.jpg", b"img", "image/jpeg"))]
        job_id = (await harness.client.post("/captures", files=files)).json()["jobId"]

        # Roda o handler do worker sincronamente para simular fim do processamento.
        await harness.service.process_job(job_id)

        response = await harness.client.get(f"/captures/{job_id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == CaptureStatus.COMPLETED.value
        # A URL absoluta é formada com base_url + caminho servido por StaticFiles.
        assert body["modelUrl"] == f"http://testserver/files/models/{job_id}.glb"
