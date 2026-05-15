"""Cache global de moldes 3D por similaridade visual (CLIP).

A interface `ModelCache` permite que o `IntegratedPipeline` consulte um GLB
ja gerado antes de pagar 3-8 min de Hunyuan e GPU. Tres pecas centrais:

- `lookup(embedding) -> CacheHit | None`: compara o embedding novo com todos
  os ja persistidos em `modelos_3d_universais` via cosine (produto interno em
  vetores L2-normalizados). Retorna o melhor match se passar o threshold.
- `store(embedding, glb_path, ...)`: persiste o molde novo (INSERT em
  `modelos_3d_universais` + copia do GLB para `storage/cache/<id>.glb`).
  Se `product_id` veio na request, faz UPSERT em `modelos_3d_produto` para
  vincular o produto comercial do tenant ao molde universal.
- Bypass `DisabledModelCache` para quando o cache esta desligado (`CACHE_ENABLED=false`)
  ou para testes que nao querem mexer no DB.

A separacao entre `modelos_3d_universais` (cache global) e `modelos_3d_produto`
(amarra produto comercial → molde, por tenant) e propositada e documentada em
[docs/09g-cache-similaridade-clip.md].
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...core.logging import get_logger
from ...storage.local_storage import LocalStorage
from .embeddings import ImageEmbedding

_log = get_logger("captures.cache")


@dataclass(frozen=True)
class CacheHit:
    """Resultado positivo de `ModelCache.lookup`."""

    universal_id: str
    glb_path: Path
    similarity: float
    hit_count: int


class ModelCache(ABC):
    """Contrato do cache de moldes universais."""

    @abstractmethod
    async def lookup(self, embedding: ImageEmbedding) -> CacheHit | None:
        """Procura o vizinho mais parecido em modelos_3d_universais.

        Retorna `CacheHit` se a similaridade cosine passar do threshold
        configurado; caso contrario, `None`.
        """

    @abstractmethod
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
        """Persiste o molde novo no cache global e (opcional) amarra ao produto.

        Retorna o `universal_id` gerado.
        """

    @abstractmethod
    async def bind_product(
        self,
        universal_id: str,
        *,
        product_id: int,
        capture_job_id: str,
    ) -> None:
        """Liga um produto comercial existente a um molde universal ja cacheado.

        Util em cache hit: o GLB nao precisa ser regerado, mas se o request
        trouxe `product_id` queremos atualizar `modelos_3d_produto` para que o
        produto deste tenant aponte para este molde. Faz UPSERT por
        `produto_id` (mantem a UNIQUE preexistente).
        """


class DisabledModelCache(ModelCache):
    """Bypass: nunca acha nada e nao persiste.

    Util para `CACHE_ENABLED=false` no .env, ambientes sem torch, ou testes
    que validam o pipeline sem cache.
    """

    async def lookup(self, embedding: ImageEmbedding) -> CacheHit | None:
        return None

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
        # Mesmo desligado retornamos um id sintetico — o pipeline continua
        # funcional. Nada toca o disco/banco.
        return f"disabled-{source_job_id}"

    async def bind_product(
        self,
        universal_id: str,
        *,
        product_id: int,
        capture_job_id: str,
    ) -> None:
        return None


class ClipSimilarityCache(ModelCache):
    """Implementacao real: cosine linear sobre embeddings em modelos_3d_universais.

    `session_factory` injetado deixa o cache testavel com SQLite em-memoria
    sem precisar de Postgres real. `storage` resolve o caminho fisico do GLB
    cacheado em `storage/cache/<id>.glb`.

    O threshold de similaridade vem do `.env` (`CACHE_SIMILARITY_THRESHOLD`)
    e e injetado no construtor para nao depender da Settings global.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: LocalStorage,
        *,
        similarity_threshold: float = 0.92,
    ):
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError(
                "similarity_threshold deve estar em (0.0, 1.0]: "
                f"{similarity_threshold}"
            )
        self._session_factory = session_factory
        self._storage = storage
        self._threshold = similarity_threshold

    # ------------------------------------------------------------------ lookup

    async def lookup(self, embedding: ImageEmbedding) -> CacheHit | None:
        import numpy as np

        query_vector = np.asarray(embedding.vector, dtype=np.float32)
        if query_vector.size == 0:
            _log.warning("Embedding vazio no lookup; tratando como miss")
            return None

        async with self._session_factory() as session:
            try:
                result = await session.execute(
                    text(
                        "SELECT id, caminho_arquivo_modelo, embedding, embedding_dim, "
                        "       hit_count "
                        "FROM modelos_3d_universais"
                    )
                )
                linhas = result.mappings().all()
            except Exception as exc:
                _log.warning("Lookup no cache falhou (%s); tratando como miss", exc)
                return None

        if not linhas:
            return None

        melhor: tuple[float, dict] | None = None
        for linha in linhas:
            try:
                cand_vector = _decode_embedding(
                    linha["embedding"],
                    linha["embedding_dim"],
                )
            except Exception as exc:
                _log.warning(
                    "Embedding corrompido em modelos_3d_universais.id=%s (%s); pulando",
                    linha["id"],
                    exc,
                )
                continue

            if cand_vector.shape != query_vector.shape:
                _log.debug(
                    "Dimensao incompativel em id=%s (%s vs %s); pulando",
                    linha["id"],
                    cand_vector.shape,
                    query_vector.shape,
                )
                continue

            # Cosine = produto interno quando ambos sao L2-normalizados.
            similarity = float(np.dot(query_vector, cand_vector))
            if melhor is None or similarity > melhor[0]:
                melhor = (similarity, dict(linha))

        if melhor is None:
            return None

        max_sim, vencedor = melhor
        if max_sim < self._threshold:
            _log.info(
                "Cache miss: maior similaridade=%.4f < threshold=%.4f",
                max_sim,
                self._threshold,
            )
            return None

        universal_id = str(vencedor["id"])
        await self._increment_hit_count(universal_id)

        _log.info(
            "Cache HIT: universal_id=%s, similarity=%.4f",
            universal_id,
            max_sim,
        )
        return CacheHit(
            universal_id=universal_id,
            glb_path=self._storage.cache_path(universal_id),
            similarity=max_sim,
            hit_count=int(vencedor["hit_count"]) + 1,
        )

    async def _increment_hit_count(self, universal_id: str) -> None:
        async with self._session_factory() as session:
            try:
                await session.execute(
                    text(
                        "UPDATE modelos_3d_universais "
                        "SET hit_count = hit_count + 1, "
                        "    ultimo_hit_em = CURRENT_TIMESTAMP "
                        "WHERE id = :id"
                    ),
                    {"id": universal_id},
                )
                await session.commit()
            except Exception as exc:
                _log.warning(
                    "Falha ao incrementar hit_count em id=%s: %s",
                    universal_id,
                    exc,
                )

    # ------------------------------------------------------------------ store

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
        import numpy as np

        universal_id = str(uuid4())
        destino_glb = self._storage.cache_path(universal_id)
        destino_glb.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(glb_path, destino_glb)
        except Exception as exc:
            _log.warning(
                "Nao consegui copiar GLB para o cache (%s -> %s): %s",
                glb_path,
                destino_glb,
                exc,
            )
            # Sem o GLB fisico no cache, o lookup futuro nao serve para nada;
            # nao registra a entrada.
            return universal_id

        vetor = np.asarray(embedding.vector, dtype=np.float32)
        embedding_bytes = vetor.tobytes()
        embedding_dim = int(vetor.shape[0]) if vetor.ndim else embedding.dim

        async with self._session_factory() as session:
            try:
                await session.execute(
                    text(
                        "INSERT INTO modelos_3d_universais ("
                        "  id, caminho_arquivo_modelo, embedding, embedding_dim, "
                        "  source_job_id, label_path, liquid_color, hit_count"
                        ") VALUES ("
                        "  :id, :path, :embedding, :dim, "
                        "  :job_id, :label_path, :liquid_color, 0"
                        ")"
                    ),
                    {
                        "id": universal_id,
                        "path": str(destino_glb),
                        "embedding": embedding_bytes,
                        "dim": embedding_dim,
                        "job_id": source_job_id,
                        "label_path": str(label_path) if label_path else None,
                        "liquid_color": liquid_color,
                    },
                )

                if product_id is not None:
                    await self._upsert_modelo_produto(
                        session,
                        product_id=product_id,
                        universal_id=universal_id,
                        glb_path=destino_glb,
                        capture_job_id=source_job_id,
                    )

                await session.commit()
            except Exception as exc:
                _log.warning(
                    "Falha ao persistir cache universal_id=%s: %s",
                    universal_id,
                    exc,
                )

        _log.info(
            "Cache store: universal_id=%s, product_id=%s",
            universal_id,
            product_id,
        )
        return universal_id

    async def bind_product(
        self,
        universal_id: str,
        *,
        product_id: int,
        capture_job_id: str,
    ) -> None:
        glb_path = self._storage.cache_path(universal_id)
        async with self._session_factory() as session:
            try:
                await self._upsert_modelo_produto(
                    session,
                    product_id=product_id,
                    universal_id=universal_id,
                    glb_path=glb_path,
                    capture_job_id=capture_job_id,
                )
                await session.commit()
            except Exception as exc:
                _log.warning(
                    "Falha ao amarrar product_id=%s ao universal=%s: %s",
                    product_id,
                    universal_id,
                    exc,
                )

    async def _upsert_modelo_produto(
        self,
        session: AsyncSession,
        *,
        product_id: int,
        universal_id: str,
        glb_path: Path,
        capture_job_id: str,
    ) -> None:
        """Liga o produto comercial (do tenant) ao molde universal recem-criado.

        ON CONFLICT (produto_id) preserva a UNIQUE da tabela existente: cada
        produto so aponta para um modelo. Em conflito, atualiza para o molde
        mais recente.
        """
        await session.execute(
            text(
                "INSERT INTO modelos_3d_produto ("
                "  produto_id, caminho_arquivo_modelo, status, "
                "  capture_job_id, modelo_universal_id, criado_em, atualizado_em"
                ") VALUES ("
                "  :produto_id, :path, 'completo', "
                "  :job_id, :universal_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                ") "
                "ON CONFLICT (produto_id) DO UPDATE SET "
                "  modelo_universal_id = EXCLUDED.modelo_universal_id, "
                "  caminho_arquivo_modelo = EXCLUDED.caminho_arquivo_modelo, "
                "  capture_job_id = EXCLUDED.capture_job_id, "
                "  status = 'completo', "
                "  atualizado_em = CURRENT_TIMESTAMP"
            ),
            {
                "produto_id": product_id,
                "path": str(glb_path),
                "job_id": capture_job_id,
                "universal_id": universal_id,
            },
        )


def _decode_embedding(raw: bytes, dim: int):
    """Desserializa um embedding bytea -> np.ndarray float32 de shape (dim,).

    Levanta se o tamanho dos bytes nao casa com `dim * 4` (float32).
    """
    import numpy as np

    esperado = int(dim) * 4
    if len(raw) != esperado:
        raise ValueError(
            f"embedding com {len(raw)} bytes nao casa com dim={dim} (esperado {esperado})"
        )
    return np.frombuffer(raw, dtype=np.float32, count=int(dim))
