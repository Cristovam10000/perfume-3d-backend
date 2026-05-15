"""Testes do ModelCache.

DisabledModelCache: lookup vazio + store/bind no-op.
ClipSimilarityCache: lookup linear, threshold, store + upsert opcional em
modelos_3d_produto. SQLite nao suporta o ON CONFLICT do Postgres com a sintaxe
que usamos no upsert real; testamos store sem product_id (alvo principal).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from app.modules.captures.cache import (
    ClipSimilarityCache,
    DisabledModelCache,
)
from app.modules.captures.embeddings import ImageEmbedding
from app.storage.local_storage import LocalStorage


def _embedding(values: list[float], paths: list[Path] | None = None) -> ImageEmbedding:
    vector = np.array(values, dtype=np.float32)
    norma = float(np.linalg.norm(vector))
    if norma > 0:
        vector = vector / norma
    return ImageEmbedding(
        vector=vector,
        dim=int(vector.shape[0]),
        source_paths=paths or [],
    )


@pytest_asyncio.fixture
async def storage(tmp_path: Path) -> LocalStorage:
    s = LocalStorage(root=tmp_path / "storage")
    s.ensure_dirs()
    return s


@pytest.mark.asyncio
async def test_disabled_cache_lookup_returns_none() -> None:
    cache = DisabledModelCache()
    result = await cache.lookup(_embedding([1.0, 0.0, 0.0, 0.0]))
    assert result is None


@pytest.mark.asyncio
async def test_disabled_cache_store_is_no_op(tmp_path: Path) -> None:
    cache = DisabledModelCache()
    glb = tmp_path / "fake.glb"
    glb.write_bytes(b"glTF...")
    id_ = await cache.store(
        _embedding([1.0, 0.0, 0.0, 0.0]),
        glb,
        source_job_id="job-1",
    )
    # Disabled retorna um id sintetico mas nao toca disco/banco.
    assert id_.startswith("disabled-")


@pytest.mark.asyncio
async def test_disabled_cache_bind_product_is_no_op() -> None:
    cache = DisabledModelCache()
    # Nao deve levantar.
    await cache.bind_product("u-1", product_id=42, capture_job_id="job-1")


@pytest.mark.asyncio
async def test_clip_cache_lookup_empty_table(session_factory, storage) -> None:
    cache = ClipSimilarityCache(session_factory, storage, similarity_threshold=0.9)
    result = await cache.lookup(_embedding([1.0, 0.0, 0.0, 0.0]))
    assert result is None


@pytest.mark.asyncio
async def test_clip_cache_store_then_lookup_hit(
    session_factory, storage, tmp_path
) -> None:
    cache = ClipSimilarityCache(session_factory, storage, similarity_threshold=0.9)

    glb = tmp_path / "fonte.glb"
    glb.write_bytes(b"glTF\x02\x00\x00\x00fake")

    emb = _embedding([1.0, 0.0, 0.0, 0.0])
    universal_id = await cache.store(emb, glb, source_job_id="job-store")
    assert universal_id
    # GLB foi copiado para storage/cache/<id>.glb.
    assert storage.cache_path(universal_id).exists()

    # Lookup com mesmo embedding -> hit similaridade ~ 1.0.
    hit = await cache.lookup(emb)
    assert hit is not None
    assert hit.universal_id == universal_id
    assert hit.similarity > 0.99
    assert hit.hit_count == 1  # foi incrementado pelo lookup


@pytest.mark.asyncio
async def test_clip_cache_miss_below_threshold(
    session_factory, storage, tmp_path
) -> None:
    cache = ClipSimilarityCache(session_factory, storage, similarity_threshold=0.95)
    glb = tmp_path / "fonte.glb"
    glb.write_bytes(b"glTF...")

    await cache.store(
        _embedding([1.0, 0.0, 0.0, 0.0]),
        glb,
        source_job_id="job-1",
    )

    # Vetor ortogonal -> cosine = 0, abaixo do threshold.
    result = await cache.lookup(_embedding([0.0, 1.0, 0.0, 0.0]))
    assert result is None


@pytest.mark.asyncio
async def test_clip_cache_picks_best_among_candidates(
    session_factory, storage, tmp_path
) -> None:
    cache = ClipSimilarityCache(session_factory, storage, similarity_threshold=0.5)

    glb1 = tmp_path / "a.glb"
    glb1.write_bytes(b"glTF a")
    glb2 = tmp_path / "b.glb"
    glb2.write_bytes(b"glTF b")

    # Duas entradas em direcoes diferentes.
    id_a = await cache.store(
        _embedding([1.0, 0.0, 0.0, 0.0]),
        glb1,
        source_job_id="job-a",
    )
    id_b = await cache.store(
        _embedding([0.7, 0.7, 0.0, 0.0]),
        glb2,
        source_job_id="job-b",
    )

    # Query proxima de B mas tambem positiva em A -> escolhe B.
    query = _embedding([0.7, 0.7, 0.0, 0.0])
    hit = await cache.lookup(query)
    assert hit is not None
    assert hit.universal_id == id_b
    assert hit.universal_id != id_a


@pytest.mark.asyncio
async def test_clip_cache_rejects_invalid_threshold(session_factory, storage) -> None:
    with pytest.raises(ValueError):
        ClipSimilarityCache(session_factory, storage, similarity_threshold=0.0)
    with pytest.raises(ValueError):
        ClipSimilarityCache(session_factory, storage, similarity_threshold=1.5)
