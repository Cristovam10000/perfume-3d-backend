"""Testes do ImageEmbedder.

DisabledEmbedder: shape e dim corretos, paths preservados.
ClipImageEmbedder: validacoes de input. O carregamento real do CLIP exige
torch+transformers e ~2GB de download; nao instanciamos o modelo nesse
arquivo (cobertura de integracao fica para teste opt-in).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.captures.embeddings import (
    ClipImageEmbedder,
    DisabledEmbedder,
    ImageEmbedding,
)


@pytest.mark.asyncio
async def test_disabled_embedder_returns_zero_vector(tmp_path: Path) -> None:
    embedder = DisabledEmbedder()
    foto = tmp_path / "fake.jpg"
    foto.write_bytes(b"fake")

    result = await embedder.embed([foto])

    assert isinstance(result, ImageEmbedding)
    assert result.dim == 512
    assert result.vector.shape == (512,)
    # Todos os valores zero.
    assert float(abs(result.vector).sum()) == 0.0
    assert result.source_paths == [foto]


@pytest.mark.asyncio
async def test_disabled_embedder_custom_dim(tmp_path: Path) -> None:
    embedder = DisabledEmbedder(dim=128)
    foto = tmp_path / "fake.jpg"
    foto.write_bytes(b"fake")

    result = await embedder.embed([foto])

    assert result.dim == 128
    assert result.vector.shape == (128,)


def test_disabled_embedder_rejects_invalid_dim() -> None:
    with pytest.raises(ValueError):
        DisabledEmbedder(dim=0)
    with pytest.raises(ValueError):
        DisabledEmbedder(dim=-5)


def test_clip_embedder_rejects_empty_model_name() -> None:
    with pytest.raises(ValueError):
        ClipImageEmbedder(model_name="")


@pytest.mark.asyncio
async def test_clip_embedder_rejects_empty_image_list() -> None:
    embedder = ClipImageEmbedder()
    with pytest.raises(ValueError):
        await embedder.embed([])
