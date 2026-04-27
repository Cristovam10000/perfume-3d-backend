"""Detector de cor do líquido a partir das fotos enviadas.

A cor extraída vira `liquid_color` no `ProcessingInput`, que o
`TemplateProcessor` repassa pro Blender como argumento `--liquid-color
#RRGGBB`. O Blender por sua vez aplica como `Base Color` no material
`water` do template.

Mesmo padrão Strategy do `Processor` e do `Classifier`: ABC + várias
implementações trocáveis por configuração.

Implementações:
- `DisabledColorDetector`: devolve sempre None (sistema usa cor default
  do template).
- `AverageColorDetector`: RGB médio do crop central das imagens. MVP —
  sem segmentação inteligente, assume frasco aproximadamente centrado.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.color_detector")


class ColorDetector(ABC):
    """Contrato dos detectores de cor."""

    @abstractmethod
    async def detect(self, images: list[Path]) -> str | None:
        """Retorna cor em formato '#RRGGBB' ou None quando não houver
        informação confiável."""


class DisabledColorDetector(ColorDetector):
    """Bypass: sempre None. Sistema usa a cor padrão do material do template."""

    async def detect(self, images: list[Path]) -> str | None:
        return None


class AverageColorDetector(ColorDetector):
    """RGB médio do crop central de cada imagem, agregado nas fotos.

    Estratégia MVP — funciona bem quando o frasco está aproximadamente
    centralizado nas fotos. Para precisão maior, evolução natural seria
    fazer segmentação (Rembg, GroundedSAM) e calcular cor só dentro da
    máscara do frasco, mas isso fica fora do escopo do MVP.
    """

    def __init__(self, crop_ratio: float = 0.4):
        if not 0.0 < crop_ratio <= 1.0:
            raise ValueError("crop_ratio deve estar em (0, 1]")
        self.crop_ratio = crop_ratio

    async def detect(self, images: list[Path]) -> str | None:
        if not images:
            return None
        return await asyncio.to_thread(self._detect_sync, images)

    def _detect_sync(self, images: list[Path]) -> str | None:
        # Lazy import — Pillow só é necessário quando o detector ativo é este.
        from PIL import Image, ImageOps

        r_total = g_total = b_total = 0.0
        n = 0

        for path in images:
            try:
                img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            except Exception as exc:
                _log.warning("Imagem invalida ignorada (%s): %s", path, exc)
                continue

            w, h = img.size
            crop_w = max(1, int(w * self.crop_ratio))
            crop_h = max(1, int(h * self.crop_ratio))
            left = (w - crop_w) // 2
            top = (h - crop_h) // 2
            crop = img.crop((left, top, left + crop_w, top + crop_h))

            pixels = _chromatic_pixels(crop)
            if not pixels:
                pixels = list(crop.getdata())
            count = len(pixels)
            r_total += sum(p[0] for p in pixels) / count
            g_total += sum(p[1] for p in pixels) / count
            b_total += sum(p[2] for p in pixels) / count
            n += 1

        if n == 0:
            return None

        r = int(round(r_total / n))
        g = int(round(g_total / n))
        b = int(round(b_total / n))
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        _log.info("Cor detectada (RGB media de %d imagens): %s", n, hex_color)
        return hex_color


def _chromatic_pixels(img) -> list[tuple[int, int, int]]:
    """Seleciona pixels coloridos e descarta fundo claro/preto neutro."""
    selected: list[tuple[int, int, int]] = []
    for r, g, b in img.getdata():
        mx = max(r, g, b)
        mn = min(r, g, b)
        saturation = mx - mn
        if saturation >= 30 and 45 <= mx <= 245 and (r + g + b) <= 650:
            selected.append((r, g, b))
    return selected
