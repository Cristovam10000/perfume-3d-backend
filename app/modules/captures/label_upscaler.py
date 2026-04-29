"""Upscale de label: aumenta a resolução da label extraída antes da projeção.

O objetivo é preservar texto real da foto do usuário com uma operação barata e
determinística. Lanczos não inventa detalhes como um super-resolution neural,
mas evita nova dependência pesada e é suficiente quando a extração já tem
algumas centenas de pixels.
"""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from pathlib import Path


class LabelUpscaler(ABC):
    """Contrato dos upscalers de label."""

    @abstractmethod
    async def upscale(
        self,
        input: Path,
        output: Path,
        target_size: int | None = None,
    ) -> Path:
        """Gera uma label ampliada preservando aspect ratio."""


class DisabledLabelUpscaler(LabelUpscaler):
    """Bypass: copia a label sem alteração. Útil em testes e fallback."""

    async def upscale(
        self,
        input: Path,
        output: Path,
        target_size: int | None = None,
    ) -> Path:
        if not input.exists():
            raise FileNotFoundError(f"Label de entrada não encontrada: {input}")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input, output)
        return output


class LanczosLabelUpscaler(LabelUpscaler):
    """Upscale com Pillow Image.resize usando Resampling.LANCZOS."""

    def __init__(self, target_size: int = 2048):
        if target_size <= 0:
            raise ValueError("target_size deve ser positivo")
        self.target_size = target_size

    async def upscale(
        self,
        input: Path,
        output: Path,
        target_size: int | None = None,
    ) -> Path:
        tamanho_alvo = target_size or self.target_size
        if tamanho_alvo <= 0:
            raise ValueError("target_size deve ser positivo")
        return await asyncio.to_thread(
            self._upscale_sync, input, output, tamanho_alvo
        )

    def _upscale_sync(self, input: Path, output: Path, target_size: int) -> Path:
        if not input.exists():
            raise FileNotFoundError(f"Label de entrada não encontrada: {input}")

        from PIL import Image

        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(input) as img:
            imagem = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
            largura, altura = imagem.size
            lado_maior = max(largura, altura)
            if lado_maior <= 0:
                raise ValueError(f"Imagem de label inválida: {input}")

            escala = target_size / lado_maior
            nova_largura = max(1, int(round(largura * escala)))
            nova_altura = max(1, int(round(altura * escala)))

            try:
                filtro = Image.Resampling.LANCZOS
            except AttributeError:  # Pillow antigo
                filtro = Image.LANCZOS

            ampliada = imagem.resize((nova_largura, nova_altura), filtro)
            ampliada.save(output, format="PNG")

        return output
