"""Classificacao de transparencia do frasco a partir das fotos.

Motivacao: o `BlenderMeshRefiner` aplica shader de vidro PBR no corpo do
frasco, mas nem todo frasco e de vidro transparente — frascos opacos (ex.:
Lattafa Asad, preto fosco) ficariam errados com transmission=1. Este
componente decide, ANTES do refinamento, se o frasco fotografado e
transparente/translucido ou opaco, usando CLIP zero-shot sobre as fotos
preprocessadas do job.

Mesmo padrao Strategy do resto do modulo:
- `DisabledTransparencyClassifier`: bypass; devolve `transparent=None`
  (desconhecido), que o pipeline traduz para o comportamento legado do
  refiner (heuristica `auto`).
- `ClipTransparencyClassifier`: zero-shot com prompts transparente/opaco,
  media das probabilidades entre as fotos do job.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.transparency_classifier")


@dataclass(frozen=True)
class TransparencyResult:
    """Veredito de transparencia para o conjunto de fotos de um job.

    `transparent` usa tres estados:
    - True  -> frasco transparente/translucido (refiner aplica vidro).
    - False -> frasco opaco (refiner preserva textura do corpo).
    - None  -> desconhecido (refiner usa heuristica legada `auto`).
    """

    transparent: bool | None
    confidence: float
    source: str = "disabled"  # "disabled" | "clip"


class TransparencyClassifier(ABC):
    """Contrato dos classificadores de transparencia."""

    @abstractmethod
    async def classify(self, image_paths: list[Path]) -> TransparencyResult: ...


class DisabledTransparencyClassifier(TransparencyClassifier):
    """Bypass: devolve `transparent=None` (desconhecido).

    O pipeline traduz None para o modo `auto` do refiner, preservando o
    comportamento legado sem exigir torch/transformers.
    """

    async def classify(self, image_paths: list[Path]) -> TransparencyResult:
        return TransparencyResult(transparent=None, confidence=0.0, source="disabled")


class ClipTransparencyClassifier(TransparencyClassifier):
    """Zero-shot CLIP: frasco transparente vs. opaco.

    Estrategia (ensemble de 4 classes, 2 por lado):
    1. Para cada foto, softmax sobre os 4 prompts; a probabilidade
       "transparente" e a soma das classes de vidro claro + vidro tintado.
    2. Tira a media entre as fotos do job.
    3. `transparent = media >= threshold`.

    Calibracao (fotos reais, CLIP ViT-B/32): vidro translucido escuro
    (Hinode Empire Sport, caso dificil) pontua ~0.41-0.49; frascos opacos
    (Lattafa Asad preto fosco) pontuam <=0.10. O default `threshold=0.30`
    fica entre os dois com margem. Vidro claro classico pontua bem acima.

    O modelo e carregado preguicosamente na primeira chamada (mesmo
    checkpoint do cache/view-router, entao o peso ja esta no disco) e a
    inferencia roda em `asyncio.to_thread`.
    """

    # Duas variantes por lado: prompt unico mostrou-se instavel (vidro
    # tintado escuro caia para "opaco"); o ensemble estabiliza o softmax.
    _PROMPTS_TRANSPARENT = (
        "a perfume bottle made of clear transparent glass with the liquid "
        "visible inside",
        "a perfume bottle made of tinted translucent glass that glows when "
        "light passes through",
    )
    _PROMPTS_OPAQUE = (
        "a perfume bottle with an opaque matte painted surface that blocks "
        "all light",
        "a perfume bottle made of solid opaque material with metallic "
        "decorations",
    )

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        threshold: float = 0.30,
    ):
        if not model_name:
            raise ValueError("model_name nao pode ser vazio")
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold deve estar em (0, 1): {threshold}")
        self.model_name = model_name
        self.threshold = threshold
        self._model = None
        self._processor = None

    async def classify(self, image_paths: list[Path]) -> TransparencyResult:
        if not image_paths:
            raise ValueError("ClipTransparencyClassifier precisa de pelo menos 1 imagem")
        return await asyncio.to_thread(self._classify_sync, image_paths)

    # ------------------------------------------------------------------ sync

    def _classify_sync(self, image_paths: list[Path]) -> TransparencyResult:
        self._ensure_loaded()

        probs: list[float] = []
        for caminho in image_paths:
            try:
                probs.append(self._prob_transparent(caminho))
            except Exception as exc:
                _log.warning("Imagem ignorada na classificacao (%s): %s", caminho, exc)

        if not probs:
            raise ValueError(
                "Nenhuma imagem valida para classificar em "
                f"{[str(p) for p in image_paths]}"
            )

        media = sum(probs) / len(probs)
        transparente = media >= self.threshold
        _log.info(
            "Transparencia: %s (prob=%.3f, threshold=%.2f, %d foto(s))",
            "transparente" if transparente else "opaco",
            media,
            self.threshold,
            len(probs),
        )
        return TransparencyResult(
            transparent=transparente,
            confidence=float(media),
            source="clip",
        )

    def _prob_transparent(self, path: Path) -> float:
        import torch

        img = _open_rgb_image(path)
        prompts = [*self._PROMPTS_TRANSPARENT, *self._PROMPTS_OPAQUE]
        inputs = self._processor(
            text=prompts,
            images=img,
            return_tensors="pt",
            padding=True,
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)[0]
        n_transp = len(self._PROMPTS_TRANSPARENT)
        return float(probs[:n_transp].sum().item())

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        _log.info("Carregando CLIP '%s' para transparencia...", self.model_name)
        self._model = CLIPModel.from_pretrained(self.model_name)
        self._processor = CLIPProcessor.from_pretrained(self.model_name)


def _open_rgb_image(path: Path):
    """Abre uma imagem respeitando orientacao EXIF antes de enviar ao CLIP."""
    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
