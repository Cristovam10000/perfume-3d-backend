from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.modules.captures.classifier import (
    Classifier,
    ClassificationResult,
    DisabledClassifier,
)
from app.modules.captures.color_detector import ColorDetector
from app.modules.captures.processor import (
    ProcessingInput,
    ProcessingResult,
    Processor,
)
from app.modules.captures.queue import ProcessingQueue
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

        # Arquivos gravados em disco.
        for img in job.images:
            assert Path(img.path).exists()


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

        job = await fx.service.get_job(job_id)
        assert job is not None
        assert job.status == CaptureStatus.COMPLETED.value
        assert job.model_path == f"/files/models/{job_id}.glb"
        assert job.error is None

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


class _StaticClassifier(Classifier):
    """Devolve sempre o mesmo template_id, ignorando as imagens."""

    def __init__(self, template_id: str):
        self.template_id = template_id

    async def classify(self, images):
        return ClassificationResult(
            template_id=self.template_id, confidence=0.9, scores={self.template_id: 0.9}
        )


class _BrokenClassifier(Classifier):
    async def classify(self, images):
        raise RuntimeError("classificador estourou")


class TestClassifierIntegration:
    @pytest.mark.asyncio
    async def test_classified_template_id_is_passed_to_processor(
        self, session_factory, tmp_path
    ):
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
            classifier=_StaticClassifier("cylindrical_basic"),
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        assert processor.calls[0].template_id == "cylindrical_basic"

    @pytest.mark.asyncio
    async def test_classifier_failure_falls_back_to_none_template_id(
        self, session_factory, tmp_path
    ):
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
            classifier=_BrokenClassifier(),
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        # Job foi processado mesmo com classifier estourando
        assert processor.calls[0].template_id is None
        job = await service.get_job(job_id)
        assert job.status == CaptureStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_default_classifier_is_disabled_with_fallback_id(
        self, session_factory, tmp_path
    ):
        # Construindo sem injetar classifier — service usa DisabledClassifier interno
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        # Disabled retorna o template fallback definido no service.
        assert processor.calls[0].template_id == "rectangular_basic"


class _StaticColorDetector(ColorDetector):
    def __init__(self, color: str | None):
        self.color = color

    async def detect(self, images):
        return self.color


class _BrokenColorDetector(ColorDetector):
    async def detect(self, images):
        raise RuntimeError("color detector estourou")


class TestColorDetectorIntegration:
    @pytest.mark.asyncio
    async def test_detected_color_is_passed_to_processor(
        self, session_factory, tmp_path
    ):
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
            color_detector=_StaticColorDetector("#FFAA00"),
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        assert processor.calls[0].liquid_color == "#FFAA00"

    @pytest.mark.asyncio
    async def test_color_detector_failure_falls_back_to_none(
        self, session_factory, tmp_path
    ):
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
            color_detector=_BrokenColorDetector(),
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        # Job foi processado mesmo com detector estourando
        assert processor.calls[0].liquid_color is None
        job = await service.get_job(job_id)
        assert job.status == CaptureStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_default_color_detector_returns_none(
        self, session_factory, tmp_path
    ):
        # Sem injecao = DisabledColorDetector → liquid_color = None
        storage = LocalStorage(root=tmp_path / "storage")
        storage.ensure_dirs()
        processor = _RecordingProcessor()
        service = CaptureService(
            session_factory,
            storage,
            processor,
            _StubQueue(),  # type: ignore[arg-type]
        )

        job_id = await service.create_job(
            [IncomingImage(filename="a.jpg", content=b"a")]
        )
        await service.process_job(job_id)

        assert processor.calls[0].liquid_color is None
