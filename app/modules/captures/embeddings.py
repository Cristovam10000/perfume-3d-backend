"""Embeddings visuais de fotos para o cache de similaridade.

Produz um vetor 512-d L2-normalizado representando o conjunto de fotos de um
job. Esse vetor e a chave do `ModelCache`: comparacoes cosine identificam
moldes 3D ja gerados para o mesmo frasco (cross-tenant).

Mesmo padrao Strategy do resto do modulo: ABC + bypass `Disabled*` + impl real.

Implementacoes disponiveis:
- `DisabledEmbedder`: retorna zeros; serve para testes e para combinar com
  `DisabledModelCache` desligando o cache inteiro sem precisar de torch.
- `ClipImageEmbedder`: usa CLIP (transformers + torch) para embedar cada
  imagem e tira o mean-pool das N imagens; L2-normaliza o resultado.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.logging import get_logger

_log = get_logger("captures.embeddings")

# Default escolhido para alinhar com CLIP ViT-B/32, que produz embeddings 512-d.
_DEFAULT_EMBEDDING_DIM = 512


@dataclass(frozen=True)
class ImageEmbedding:
    """Embedding agregado das fotos de um job, pronto para o cache."""

    vector: Any  # np.ndarray shape (D,) float32 L2-normalizado
    dim: int
    source_paths: list[Path] = field(default_factory=list)


class ImageEmbedder(ABC):
    """Contrato dos embedders."""

    @abstractmethod
    async def embed(self, image_paths: list[Path]) -> ImageEmbedding:
        """Calcula o embedding agregado das fotos do job."""


class DisabledEmbedder(ImageEmbedder):
    """Bypass: retorna vetor zero. Usado em testes e quando o cache esta desligado.

    Combinado com `DisabledModelCache`, permite rodar o pipeline sem instalar
    torch/transformers — o cache lookup vira sempre miss e nada e persistido.
    """

    def __init__(self, dim: int = _DEFAULT_EMBEDDING_DIM):
        if dim <= 0:
            raise ValueError("dim deve ser positivo")
        self.dim = dim

    async def embed(self, image_paths: list[Path]) -> ImageEmbedding:
        # Import lazy para nao exigir numpy quando tudo o que se quer e o bypass.
        import numpy as np

        vector = np.zeros(self.dim, dtype=np.float32)
        return ImageEmbedding(
            vector=vector,
            dim=self.dim,
            source_paths=list(image_paths),
        )


class ClipImageEmbedder(ImageEmbedder):
    """Embedder real: CLIP via HuggingFace transformers.

    Estrategia:
    1. Para cada imagem em image_paths, abre via PIL, corrige EXIF, passa pelo
       image_processor do CLIP.
    2. Roda o vision_model (forward) -> vetor 512-d por imagem.
    3. Mean-pool dos vetores das N imagens -> 1 vetor de dim D.
    4. L2-normaliza (cosine vira produto interno trivial).

    O modelo e carregado preguicosamente na primeira chamada e reutilizado nas
    seguintes. A inferencia roda em `asyncio.to_thread` para nao bloquear o
    event loop do FastAPI.
    """

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32"):
        if not model_name:
            raise ValueError("model_name nao pode ser vazio")
        self.model_name = model_name
        self._model = None
        self._processor = None

    async def embed(self, image_paths: list[Path]) -> ImageEmbedding:
        if not image_paths:
            raise ValueError("ClipImageEmbedder precisa de pelo menos 1 imagem")
        return await asyncio.to_thread(self._embed_sync, image_paths)

    # ------------------------------------------------------------------ sync

    def _embed_sync(self, image_paths: list[Path]) -> ImageEmbedding:
        # Imports lazy: modulo carrega mesmo sem torch instalado.
        import numpy as np
        import torch

        self._ensure_loaded()
        assert self._model is not None and self._processor is not None

        vetores: list[Any] = []
        for caminho in image_paths:
            try:
                img = _open_rgb_image(caminho)
            except Exception as exc:
                _log.warning("Imagem invalida ignorada (%s): %s", caminho, exc)
                continue

            inputs = self._processor(images=img, return_tensors="pt")
            with torch.no_grad():
                features = self._model.get_image_features(**inputs)
            vetor = features[0].detach().cpu().numpy().astype(np.float32)
            vetores.append(vetor)

        if not vetores:
            raise ValueError(
                "Nenhuma imagem valida para embedar em "
                f"{[str(p) for p in image_paths]}"
            )

        # Mean-pool + L2-normalize.
        media = np.mean(np.stack(vetores, axis=0), axis=0)
        norma = float(np.linalg.norm(media))
        if norma > 0:
            media = media / norma
        else:
            _log.warning(
                "Embedding com norma zero em %d imagem(ns) — usando vetor cru",
                len(vetores),
            )

        _log.info(
            "Embedding gerado (%d imagens, dim=%d)",
            len(vetores),
            media.shape[0],
        )
        return ImageEmbedding(
            vector=media.astype(np.float32),
            dim=int(media.shape[0]),
            source_paths=list(image_paths),
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        _log.info("Carregando CLIP '%s' para embeddings...", self.model_name)
        self._model = CLIPModel.from_pretrained(self.model_name)
        self._processor = CLIPProcessor.from_pretrained(self.model_name)


def _open_rgb_image(path: Path):
    """Abre uma imagem respeitando orientacao EXIF antes de enviar ao CLIP."""
    from PIL import Image, ImageOps  # imports preguicosos

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
