"""Testes do IntegratedPipeline.

Os stages sao stubs in-process — nada toca rede, GPU ou disco real (alem de
copias byte-a-byte). Valida tres caminhos:

1. **Cache HIT**: lookup retorna entrada -> pula Hunyuan e pos-proc, serve GLB
   cacheado.
2. **Cache MISS**: roda toda a cadeia ate label projector e persiste no cache.
3. **Hunyuan falha**: levanta no Hunyuan e o job morre com ProcessingError —
   nao ha mais fallback de template.
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
from app.modules.captures.view_texture_projector import (
    AXIS_BACK,
    AXIS_TOP,
    ViewTextureProjectionInput,
    ViewTextureProjectionResult,
    ViewTextureProjector,
)
from app.modules.captures.view_router import LabeledViewRouter, ViewRouter
from app.modules.captures.mesh_refiner import (
    MeshRefiner,
    RefinementInput,
    RefinementResult,
)
from app.modules.captures.pipeline import IntegratedPipeline
from app.modules.captures.processor import (
    Hunyuan3DProcessor,
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


class SpyViewTextureProjector(ViewTextureProjector):
    """Registra as chamadas para os testes verificarem se o stage disparou."""

    def __init__(self, falhar: bool = False):
        self.chamadas: list[ViewTextureProjectionInput] = []
        self.falhar = falhar

    async def project(
        self, input: ViewTextureProjectionInput
    ) -> ViewTextureProjectionResult:
        self.chamadas.append(input)
        if self.falhar:
            raise RuntimeError("blender morreu (stub)")
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return ViewTextureProjectionResult(output_glb=input.output_glb)


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
    label_extractor: LabelExtractor | None = None,
    mesh_refiner: MeshRefiner | None = None,
    transparency_classifier: TransparencyClassifier | None = None,
    top_projector: ViewTextureProjector | None = None,
    back_projector: ViewTextureProjector | None = None,
    view_router: "ViewRouter | None" = None,
    top_elongation_max: float = 1.35,
):
    return IntegratedPipeline(
        preprocessor=CopyPreprocessor(),
        background_remover=CopyBackgroundRemover(),
        embedder=DisabledEmbedder(),
        cache=cache,
        hunyuan=hunyuan,
        mesh_refiner=mesh_refiner or CopyMeshRefiner(),
        label_extractor=label_extractor or FakeLabelExtractor(),
        label_upscaler=CopyLabelUpscaler(),
        label_projector=CopyLabelProjector(),
        storage=storage,
        transparency_classifier=transparency_classifier,
        top_projector=top_projector,
        back_projector=back_projector,
        view_router=view_router,
        top_elongation_max=top_elongation_max,
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
async def test_hunyuan_failure_raises(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    """Sem fallback de template, falha do Hunyuan mata o job."""
    cache = FakeCache(hit=None)
    pipe = _make_pipeline(
        storage,
        cache=cache,
        hunyuan=FailingHunyuan(),
    )

    with pytest.raises(ProcessingError):
        await pipe.process(
            ProcessingInput(
                job_id="job-die",
                image_paths=fotos,
                output_path=tmp_path / "out.glb",
            )
        )


# ------------------------------------------------- projecao da textura do topo


@pytest.fixture
def fotos_com_topo(tmp_path: Path) -> list[Path]:
    """5 fotos: 4 cardeais + 1 do topo, na ordem que o app enviaria."""
    pasta = tmp_path / "uploads_topo"
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = []
    for i in range(5):
        p = pasta / f"{i:02d}.jpg"
        p.write_bytes(b"\xff\xd8jpeg-stub")
        caminhos.append(p)
    return caminhos


_HINTS_COM_TOPO = ["front", "left", "back", "right", "top"]


@pytest.mark.asyncio
async def test_top_projector_dispara_quando_app_rotula_topo(
    storage: LocalStorage, fotos_com_topo: list[Path], tmp_path: Path
):
    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        top_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-topo",
            image_paths=fotos_com_topo,
            output_path=tmp_path / "out.glb",
            views=_HINTS_COM_TOPO,
        )
    )

    assert len(espiao.chamadas) == 1
    # Recebe a foto MASCARADA (pos-rembg), nao a original — o recorte por alpha
    # depende do canal de transparencia.
    assert espiao.chamadas[0].photo.suffix == ".png"
    assert espiao.chamadas[0].photo.stem.endswith("04")


@pytest.mark.asyncio
async def test_top_projector_pulado_sem_rotulo_top(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    """Sem foto marcada como `top`, o stage e no-op — nao e erro."""
    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        top_projector=espiao,
    )

    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-sem-topo",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
        )
    )

    assert espiao.chamadas == []
    assert resultado.output_path.exists()


@pytest.mark.asyncio
async def test_top_projector_falha_degrada_sem_derrubar_job(
    storage: LocalStorage, fotos_com_topo: list[Path], tmp_path: Path
):
    espiao = SpyViewTextureProjector(falhar=True)
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        top_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    saida = tmp_path / "out.glb"
    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-topo-falha",
            image_paths=fotos_com_topo,
            output_path=saida,
            views=_HINTS_COM_TOPO,
        )
    )

    assert len(espiao.chamadas) == 1
    assert resultado.output_path == saida
    assert saida.exists()  # GLB do stage anterior foi entregue


# ------------------------------------------- material declarado pelo cliente


@pytest.mark.asyncio
async def test_material_do_cliente_curto_circuita_o_clip(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    """`material=opaque` decide o body_mode sem consultar o classificador.

    O CLIP nao separa as classes de forma confiavel (docs/16: um frasco de
    vidro pontuou abaixo de um opaco), entao a resposta do usuario vence.
    """
    classificador = FakeTransparencyClassifier(transparent=True)  # diria "glass"
    refiner = CopyMeshRefiner()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
        transparency_classifier=classificador,
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-opaco",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
            material="opaque",
        )
    )

    assert classificador.called == 0, "CLIP nao deveria rodar com material explicito"
    assert refiner.inputs[0].body_mode == "keep"


@pytest.mark.asyncio
async def test_material_glass_do_cliente_forca_vidro(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    classificador = FakeTransparencyClassifier(transparent=False)  # diria "keep"
    refiner = CopyMeshRefiner()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
        transparency_classifier=classificador,
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-vidro",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
            material="glass",
        )
    )

    assert classificador.called == 0
    assert refiner.inputs[0].body_mode == "glass"


@pytest.mark.asyncio
async def test_sem_material_o_clip_decide(
    storage: LocalStorage, fotos: list[Path], tmp_path: Path
):
    classificador = FakeTransparencyClassifier(transparent=True)
    refiner = CopyMeshRefiner()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        mesh_refiner=refiner,
        transparency_classifier=classificador,
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-auto",
            image_paths=fotos,
            output_path=tmp_path / "out.glb",
        )
    )

    assert classificador.called == 1
    assert refiner.inputs[0].body_mode == "glass"


@pytest.mark.asyncio
async def test_clip_de_transparencia_nao_recebe_a_foto_do_topo(
    storage: LocalStorage, fotos_com_topo: list[Path], tmp_path: Path
):
    """A foto do topo tem reflexo da tampa metalica e enviesa o voto para vidro.

    Ela e a 5a do lote; o classificador deve receber so as 4 cardeais.
    """
    recebidas: list[list[Path]] = []

    class Espiao(FakeTransparencyClassifier):
        async def classify(self, image_paths):
            recebidas.append(list(image_paths))
            return await super().classify(image_paths)

    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        transparency_classifier=Espiao(transparent=False),
        view_router=LabeledViewRouter(),
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-clip-cardeais",
            image_paths=fotos_com_topo,
            output_path=tmp_path / "out.glb",
            views=_HINTS_COM_TOPO,
        )
    )

    assert len(recebidas) == 1
    assert len(recebidas[0]) == 4
    # `_safe_preprocess` prefixa a posicao: 01_..05_. O topo e a 5a do lote, e
    # os prefixos sao a unica parte estavel do nome (o resto vem do tmp_path).
    assert not any(p.stem.startswith("05_") for p in recebidas[0]), (
        "a foto do topo vazou para o CLIP"
    )
    assert {p.stem[:3] for p in recebidas[0]} == {"01_", "02_", "03_", "04_"}


# ---------------------------------------------------- guarda da foto de topo


def _escrever_png(caminho: Path, largura: int, altura: int) -> None:
    """PNG RGBA com um retangulo opaco centralizado sobre fundo transparente."""
    from PIL import Image

    img = Image.new("RGBA", (largura + 40, altura + 40), (0, 0, 0, 0))
    for x in range(20, 20 + largura):
        for y in range(20, 20 + altura):
            img.putpixel((x, y), (200, 200, 200, 255))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho)


def _lote_png(pasta: Path, altura_topo: int) -> list[Path]:
    """4 cardeais quadradas + 1 topo com a altura pedida (controla a elongacao)."""
    caminhos = []
    for i in range(4):
        p = pasta / f"{i:02d}.png"
        _escrever_png(p, 60, 60)
        caminhos.append(p)
    topo = pasta / "04.png"
    _escrever_png(topo, 40, altura_topo)
    caminhos.append(topo)
    return caminhos


@pytest.mark.asyncio
async def test_foto_de_topo_alongada_e_rejeitada(
    storage: LocalStorage, tmp_path: Path
):
    """Foto obliqua do frasco inteiro tem silhueta alongada; o stage e pulado.

    Foi o que aconteceu no job 3901ff83: o projetor estica a imagem inteira
    sobre a tampa sem procurar a tampa dentro dela, entao uma foto de perfil
    vira o frasco amassado no topo do modelo — sem levantar erro nenhum.
    """
    caminhos = _lote_png(tmp_path / "uploads_topo_ruim", altura_topo=160)

    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        top_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-topo-ruim",
            image_paths=caminhos,
            output_path=tmp_path / "out.glb",
            views=_HINTS_COM_TOPO,
        )
    )

    assert espiao.chamadas == []
    assert resultado.output_path.exists(), "o job conclui normalmente"
    assert "foto de topo ignorada" in resultado.message


@pytest.mark.asyncio
async def test_foto_de_topo_compacta_e_aceita(storage: LocalStorage, tmp_path: Path):
    caminhos = _lote_png(tmp_path / "uploads_topo_bom", altura_topo=40)

    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        top_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-topo-bom",
            image_paths=caminhos,
            output_path=tmp_path / "out.glb",
            views=_HINTS_COM_TOPO,
        )
    )

    assert len(espiao.chamadas) == 1
    assert espiao.chamadas[0].axis == AXIS_TOP
    assert "foto de topo ignorada" not in resultado.message


# --------------------------------------------------- projecao das costas


def _lote_cardeais(pasta: Path) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = []
    for i in range(4):
        p = pasta / f"{i:02d}.jpg"
        p.write_bytes(b"\xff\xd8jpeg-stub")
        caminhos.append(p)
    return caminhos


_HINTS_CARDEAIS = ["front", "left", "back", "right"]


@pytest.mark.asyncio
async def test_back_projector_dispara_em_frasco_opaco(
    storage: LocalStorage, tmp_path: Path
):
    """O Hunyuan textura com UMA foto e inventa o verso; a foto real substitui."""
    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        back_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    await pipe.process(
        ProcessingInput(
            job_id="job-costas",
            image_paths=_lote_cardeais(tmp_path / "quatro"),
            output_path=tmp_path / "out.glb",
            views=_HINTS_CARDEAIS,
            material="opaque",
        )
    )

    assert len(espiao.chamadas) == 1
    assert espiao.chamadas[0].axis == AXIS_BACK
    # Recebe a foto MASCARADA — o recorte por alpha depende da transparencia.
    assert espiao.chamadas[0].photo.suffix == ".png"
    assert espiao.chamadas[0].photo.stem.endswith("02"), "deve ser a 3a (back)"


@pytest.mark.asyncio
async def test_back_projector_pulado_em_frasco_de_vidro(
    storage: LocalStorage, tmp_path: Path
):
    """Num frasco de vidro o verso e visto ATRAVES da frente.

    Colar uma foto opaca nas faces traseiras mataria a transmissao — o
    resultado seria pior do que o palpite do gerador.
    """
    espiao = SpyViewTextureProjector()
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        back_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-costas-vidro",
            image_paths=_lote_cardeais(tmp_path / "quatro_vidro"),
            output_path=tmp_path / "out.glb",
            views=_HINTS_CARDEAIS,
            material="glass",
        )
    )

    assert espiao.chamadas == []
    assert resultado.output_path.exists()


@pytest.mark.asyncio
async def test_back_projector_falha_degrada_sem_derrubar_job(
    storage: LocalStorage, tmp_path: Path
):
    espiao = SpyViewTextureProjector(falhar=True)
    pipe = _make_pipeline(
        storage,
        cache=FakeCache(hit=None),
        hunyuan=StubHunyuan(),
        back_projector=espiao,
        view_router=LabeledViewRouter(),
    )

    saida = tmp_path / "out.glb"
    resultado = await pipe.process(
        ProcessingInput(
            job_id="job-costas-falha",
            image_paths=_lote_cardeais(tmp_path / "quatro_falha"),
            output_path=saida,
            views=_HINTS_CARDEAIS,
            material="opaque",
        )
    )

    assert len(espiao.chamadas) == 1
    assert resultado.output_path == saida
    assert saida.exists()  # GLB do stage anterior foi entregue
