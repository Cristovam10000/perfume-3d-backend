from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.modules.captures.processor import (
    ProcessingInput,
    ProcessingResult,
    Processor,
)
from app.modules.captures.service import CaptureService, IncomingImage
from app.modules.captures.status import CaptureStatus
from app.storage.local_storage import LocalStorage


class _RecordingProcessor(Processor):
    """Processor fake que grava os inputs e opcionalmente estoura."""

    def __init__(self, should_fail: bool = False):
        self.calls: list[ProcessingInput] = []
        self.should_fail = should_fail

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self.calls.append(input)
        if self.should_fail:
            raise RuntimeError("falha simulada no pipeline")
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(b"fake-glb")
        return ProcessingResult(output_path=input.output_path, message="ok")


class _StubQueue:
    """Captura o que o service tentaria filar, sem rodar nada."""

    def __init__(self):
        self.submitted: list[str] = []

    async def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


@dataclass
class _Fixtures:
    service: CaptureService
    processor: _RecordingProcessor
    queue: _StubQueue
    storage: LocalStorage


def _make_fixtures(session_factory, tmp_path: Path, *, fail: bool = False) -> _Fixtures:
    storage = LocalStorage(root=tmp_path / "storage")
    storage.ensure_dirs()
    processor = _RecordingProcessor(should_fail=fail)
    queue = _StubQueue()
    service = CaptureService(session_factory, storage, processor, queue)  # type: ignore[arg-type]
    return _Fixtures(service=service, processor=processor, queue=queue, storage=storage)


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_rejects_empty_image_list(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)
        with pytest.raises(ValidationError):
            await fx.service.create_job([])
        assert fx.queue.submitted == []

    @pytest.mark.asyncio
    async def test_persists_job_and_images_and_enqueues(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)

        images = [
            IncomingImage(filename="001.jpg", content=b"\xff\xd8\xff\x00img1"),
            IncomingImage(filename="002.jpg", content=b"\xff\xd8\xff\x00img2"),
        ]
        job_id = await fx.service.create_job(images)

        # Fila recebeu exatamente este jobId.
        assert fx.queue.submitted == [job_id]

        # Job existe no DB com status inicial e 2 imagens salvas.
        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.WAITING.value
        assert len(job.images) == 2
        # product_id nao foi passado -> None.
        assert job.product_id is None

        # Arquivos gravados em disco.
        for img in job.images:
            assert Path(img.path).exists()

    @pytest.mark.asyncio
    async def test_create_job_persists_product_id_when_passed(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)
        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")],
            product_id=99,
        )
        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.product_id == 99


class TestProcessJob:
    @pytest.mark.asyncio
    async def test_happy_path_marks_completed_with_model_url(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await fx.service.process_job(job_id)

        # Processor recebeu o output_path correto.
        assert len(fx.processor.calls) == 1
        call = fx.processor.calls[0]
        assert call.job_id == job_id
        assert call.output_path == fx.storage.model_path(job_id)
        assert call.product_id is None

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.COMPLETED.value
        assert job.model_path == f"/files/models/{job_id}.glb"
        assert job.error is None

    @pytest.mark.asyncio
    async def test_product_id_propagates_to_processor(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path)
        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")],
            product_id=42,
        )
        await fx.service.process_job(job_id)
        # O ProcessingInput recebeu product_id=42 lido do banco.
        assert fx.processor.calls[0].product_id == 42

    @pytest.mark.asyncio
    async def test_processor_failure_marks_error_and_rethrows(
        self, session_factory, tmp_path
    ):
        fx = _make_fixtures(session_factory, tmp_path, fail=True)

        job_id = await fx.service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        with pytest.raises(RuntimeError):
            await fx.service.process_job(job_id)

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.ERROR.value
        assert job.error is not None
        assert "falha simulada" in job.error

    @pytest.mark.asyncio
    async def test_nonexistent_job_is_silently_skipped(self, session_factory, tmp_path):
        fx = _make_fixtures(session_factory, tmp_path)
        # Nenhum processor.call deve acontecer.
        await fx.service.process_job("job-que-nao-existe")
        assert fx.processor.calls == []
