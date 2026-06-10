"""Testes do IntegratedPipeline.

Os stages sao stubs in-process — nada toca rede, GPU ou disco real (alem de
copias byte-a-byte). Valida tres caminhos:

1. **Cache HIT**: lookup retorna entrada -> pula Hunyuan e pos-proc, serve GLB
   cacheado.
2. **Cache MISS**: roda toda a cadeia ate label projector e persiste no cache.
3. **Hunyuan falha + fallback**: levanta no Hunyuan, IntegratedPipeline cai no
   TemplateProcessor injetado.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from app.modules.captures.cache import CacheHit, DisabledModelCache, ModelCache
from app.modules.captures.embeddings import (
    DisabledEmbedder,
    ImageEmbedder,
    ImageEmbedding,
)
from app.modules.captures.label_extractor import (
    ExtractedLabel,
    LabelExtractor,
)
from app.modules.captures.label_projector import (
    LabelProjectionInput,
    LabelProjectionResult,
    LabelProjector,
)
from app.modules.captures.label_upscaler import LabelUpscaler
from app.modules.captures.mesh_cleaner import (
    MeshCleaner,
    MeshCleanupInput,
    MeshCleanupResult,
)
from app.modules.captures.mesh_refiner import (
    MeshRefiner,
    RefinementInput,
    RefinementResult,
)
from app.modules.captures.pipeline import IntegratedPipeline
from app.modules.captures.processor import (
    Hunyuan3DProcessor,
    Processor,
    ProcessingError,
    ProcessingInput,
    ProcessingResult,
)
from app.modules.captures.transparency_classifier import (
    TransparencyClassifier,
    TransparencyResult,
)
from app.storage.local_storage import LocalStorage


# ----------------------------------------------------------------- stubs


class CopyPreprocessor:
    async def preprocess(self, input_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path


class CopyBackgroundRemover:
    async def remove(self, image_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, output_path)
        return output_path


@dataclass
class FakeCache(ModelCache):
    """Cache controlavel por teste: pode forcar hit ou miss."""

    hit: CacheHit | None = None
    stored: list[tuple[ImageEmbedding, Path, dict]] | None = None
    bound: list[tuple[str, int, str]] | None = None

    def __post_init__(self) -> None:
        if self.stored is None:
            self.stored = []
        if self.bound is None:
            self.bound = []

    async def lookup(self, embedding: ImageEmbedding) -> CacheHit | None:
        return self.hit

    async def store(
        self,
        embedding: ImageEmbedding,
        glb_path: Path,
        *,
        source_job_id: str,
        product_id: int | None = None,
        label_path: Path | None = None,
        liquid_color: str | None = None,
    ) -> str:
        assert self.stored is not None
        self.stored.append((embedding, glb_path, {
            "source_job_id": source_job_id,
            "product_id": product_id,
        }))
        return "stored-id"

    async def bind_product(
        self,
        universal_id: str,
        *,
        product_id: int,
        capture_job_id: str,
    ) -> None:
        assert self.bound is not None
        self.bound.append((universal_id, product_id, capture_job_id))


class StubHunyuan(Hunyuan3DProcessor):
    """Hunyuan que apenas escreve um GLB sintetico no output_path."""

    def __init__(self):
        super().__init__()
        self.called = 0

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self.called += 1
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(b"glTF\x02\x00\x00\x00raw")
        return ProcessingResult(
            output_path=input.output_path,
            message=f"stub hunyuan ({len(input.image_paths)})",
        )


class FailingHunyuan(Hunyuan3DProcessor):
    def __init__(self):
        super().__init__()

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        raise ProcessingError("hunyuan offline (stub)")


class CopyMeshCleaner(MeshCleaner):
    async def clean(self, input: MeshCleanupInput) -> MeshCleanupResult:
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return MeshCleanupResult(
            output_glb=input.output_glb,
            islands_removed=0,
            holes_filled=0,
            final_face_count=0,
        )


class CopyMeshRefiner(MeshRefiner):
    def __init__(self):
        self.inputs: list[RefinementInput] = []

    async def refine(self, input: RefinementInput) -> RefinementResult:
        self.inputs.append(input)
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return RefinementResult(
            output_glb=input.output_glb,
            message="stub refiner",
        )


class FakeTransparencyClassifier(TransparencyClassifier):
    """Veredito fixo, configurável por teste."""

    def __init__(self, transparent: bool | None, *, fail: bool = False):
        self.transparent = transparent
        self.fail = fail
        self.called = 0

    async def classify(self, image_paths) -> TransparencyResult:
        self.called += 1
        if self.fail:
            raise RuntimeError("classificador quebrou (stub)")
        return TransparencyResult(
            transparent=self.transparent,
            confidence=0.9 if self.transparent is not None else 0.0,
            source="stub",
        )


class NoLabelExtractor(LabelExtractor):
    """Sem label encontrada — exercita o degrade."""

    async def extract(self, image_path, mask_path, output_path):
        return None


class FakeLabelExtractor(LabelExtractor):
    """Devolve uma label com confidence alta."""

    async def extract(self, image_path, mask_path, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"PNG-stub")
        return ExtractedLabel(
            image_path=output_path,
            confidence=0.9,
            aspect_ratio=1.5,
        )


class CopyLabelUpscaler(LabelUpscaler):
    async def upscale(self, input, output, target_size=None):
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input, output)
        return output


class CopyLabelProjector(LabelProjector):
    async def project(self, input: LabelProjectionInput) -> LabelProjectionResult:
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return LabelProjectionResult(
            output_glb=input.output_glb,
            target_face_index=0,
            coverage_ratio=0.5,
        )


class StubTemplate(Processor):
    """TemplateProcessor de fallback que escreve um GLB sintetico."""

    def __init__(self):
        self.called = 0

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self.called += 1
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(b"glTF\x02\x00\x00\x00template")
        return ProcessingResult(
            output_path=input.output_path,
            message="stub template fallback",
        )


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    s = LocalStorage(root=tmp_path / "storage")
    s.ensure_dirs()
    return s


@pytest.fixture
def fotos(tmp_path: Path) -> list[Path]:
    pasta = tmp_path / "uploads"
    pasta.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(2):
        p = pasta / f"{i:02d}.jpg"
        p.write_bytes(b"\xff\xd8jpeg-stub")
        paths.append(p)
    return paths


def _make_pipeline(
    storage: LocalStorage,
    *,
    cache: ModelCache,
    hunyuan: Hunyuan3DProcessor,
    fallback: Processor | None = None,
    label_extractor: LabelExtractor | None = None,
    mesh_refiner: MeshRefiner | None = None,
    transparency_classifier: TransparencyClassifier | None = None,
):
    return IntegratedPipeline(
        preprocessor=CopyPreprocessor(),
        background_remover=CopyBackgroundRemover(),
        embedder=DisabledEmbedder(),
        cache=cache,
        hunyuan=hunyuan,
        mesh_cleaner=CopyMeshCleaner(),
        mesh_refiner=mesh_refiner or CopyMeshRefiner(),
        label_extractor=label_extractor or FakeLabelExtractor(),
        label_upscaler=CopyLabelUpscaler(),
        label_projector=CopyLabelProjector(),
        storage=storage,
        transparency_classifier=transparency_classifier,
        fallback_processor=fallback,
    )


# ----------------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_pipeline(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cached_glb = storage.cache_path("U-test")
    cached_glb.parent.mkdir(parents=True, exist_ok=True)
    cached_glb.write_bytes(b"glTF\x02\x00\x00\x00cached")

    hit = CacheHit(
        universal_id="U-test",
        glb_path=cached_glb,
        similarity=0.97,
        hit_count=5,
    )
    hunyuan = StubHunyuan()
    cache = FakeCache(hit=hit)

    pipe = _make_pipeline(storage, cache=cache, hunyuan=hunyuan)

    output = tmp_path / "out.glb"
    result = await pipe.process(
        ProcessingInput(
            job_id="job-hit",
            image_paths=fotos,
            output_path=output,
        )
    )

    assert hunyuan.called == 0
    assert result.origem == "cache"
    assert result.similarity == 0.97
    assert "similaridade=0.970" in result.message
    assert output.exists()
    # Cache nao recebeu store (nao precisa) — store fica vazio.
    assert cache.stored == []


@pytest.mark.asyncio
async def test_cache_hit_with_product_id_binds_product(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cached_glb = storage.cache_path("U-bind")
    cached_glb.parent.mkdir(parents=True, exist_ok=True)
    cached_glb.write_bytes(b"glTF\x02\x00\x00\x00cached")

    hit = CacheHit(
        universal_id="U-bind",
        glb_path=cached_glb,
        similarity=0.95,
        hit_count=1,
    )
    cache = FakeCache(hit=hit)
    pipe = _make_pipeline(storage, cache=cache, hunyuan=StubHunyuan())

    await pipe.process(
        ProcessingInput(
            job_id="job-bind",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
            product_id=42,
        )
    )

    assert cache.bound == [("U-bind", 42, "job-bind")]


@pytest.mark.asyncio
async def test_cache_miss_runs_full_pipeline_and_stores(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cache = FakeCache(hit=None)
    hunyuan = StubHunyuan()
    pipe = _make_pipeline(storage, cache=cache, hunyuan=hunyuan)

    output = tmp_path / "out.glb"
    result = await pipe.process(
        ProcessingInput(
            job_id="job-miss",
            image_paths=fotos,
            output_path=output,
            product_id=99,
        )
    )

    assert hunyuan.called == 1
    assert result.origem == "generated"
    assert output.exists()
    # Store foi chamado uma vez com product_id propagado.
    assert len(cache.stored) == 1
    _, _, meta = cache.stored[0]
    assert meta["source_job_id"] == "job-miss"
    assert meta["product_id"] == 99


@pytest.mark.asyncio
async def test_no_label_degrades_gracefully(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cache = FakeCache(hit=None)
    pipe = _make_pipeline(
        storage,
        cache=cache,
        hunyuan=StubHunyuan(),
        label_extractor=NoLabelExtractor(),
    )

    output = tmp_path / "out.glb"
    result = await pipe.process(
        ProcessingInput(
            job_id="job-nolabel",
            image_paths=fotos,
            output_path=output,
        )
    )
    # Sem label, o GLB final ainda existe (e o refined.glb).
    assert output.exists()
    assert result.origem == "generated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transparent", "body_mode_esperado"),
    [
        (True, "glass"),
        (False, "keep"),
        (None, "auto"),
    ],
)
async def test_transparency_verdict_sets_refiner_body_mode(
    storage: LocalStorage,
    fotos: list[Path],
    tmp_path: Path,
    transparent: bool | None,
    body_mode_esperado: str,
):
    refiner = CopyMeshRefiner()
    classifier = FakeTransparencyClassifier(transparent)
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
        transparency_classifier=classifier,
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-transp",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
        )
    )

    assert classifier.called == 1
    assert len(refiner.inputs) == 1
    assert refiner.inputs[0].body_mode == body_mode_esperado


@pytest.mark.asyncio
async def test_transparency_failure_degrades_to_auto(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    refiner = CopyMeshRefiner()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
        transparency_classifier=FakeTransparencyClassifier(True, fail=True),
    )

    output = tmp_path / "out.glb"
    result = await pipe.process(
        ProcessingInput(
            job_id="job-transp-fail",
            image_paths=fotos,
            output_path=output,
        )
    )

    assert result.origem == "generated"
    assert output.exists()
    assert refiner.inputs[0].body_mode == "auto"


@pytest.mark.asyncio
async def test_default_classifier_is_disabled_and_uses_auto(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    """Sem classificador injetado, o pipeline usa Disabled -> body_mode=auto."""
    refiner = CopyMeshRefiner()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-default",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
        )
    )

    assert refiner.inputs[0].body_mode == "auto"


@pytest.mark.asyncio
async def test_hunyuan_failure_uses_fallback(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cache = FakeCache(hit=None)
    fallback = StubTemplate()
    pipe = _make_pipeline(
        storage,
        cache=cache,
        hunyuan=FailingHunyuan(),
        fallback=fallback,
    )

    output = tmp_path / "out.glb"
    result = await pipe.process(
        ProcessingInput(
            job_id="job-fallback",
            image_paths=fotos,
            output_path=output,
        )
    )

    assert fallback.called == 1
    assert result.origem == "template-fallback"
    assert output.exists()


@pytest.mark.asyncio
async def test_hunyuan_failure_without_fallback_raises(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    cache = FakeCache(hit=None)
    pipe = _make_pipeline(
        storage,
        cache=cache,
        hunyuan=FailingHunyuan(),
        fallback=None,
    )

    with pytest.raises(ProcessingError):
        await pipe.process(
            ProcessingInput(
                job_id="job-die",
                image_paths=fotos,
                output_path=tmp_path / "out.glb",
            )
        )
