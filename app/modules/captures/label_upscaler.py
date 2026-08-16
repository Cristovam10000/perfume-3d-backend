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
    """Upscale com Pillow Image.resize usando Resampling.LANCZOS.

    O `unsharp` compensa a suavização que qualquer reamostragem introduz. Não
    inventa detalhe — realça o que sobreviveu ao redimensionamento, que é o que
    decide se o texto da label fica legível no modelo. Vale tanto na ampliação
    (Lanczos borra) quanto na redução (o recorte agora sai da foto original, em
    resolução maior que o alvo).
    """

    def __init__(
        self,
        target_size: int = 2048,
        unsharp: bool = True,
        unsharp_raio: float = 1.2,
        unsharp_forca: float = 0.6,
    ):
        if target_size <= 0:
            raise ValueError("target_size deve ser positivo")
        if unsharp_raio <= 0:
            raise ValueError("unsharp_raio deve ser positivo")
        if not 0.0 <= unsharp_forca <= 3.0:
            raise ValueError("unsharp_forca deve estar em [0, 3]")
        self.target_size = target_size
        self.unsharp = unsharp
        self.unsharp_raio = unsharp_raio
        self.unsharp_forca = unsharp_forca

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
            if self.unsharp:
                ampliada = self._aplicar_unsharp(ampliada)
            ampliada.save(output, format="PNG")

        return output

    def _aplicar_unsharp(self, imagem):
        """Realce de borda preservando o canal alpha.

        `UnsharpMask` do Pillow trabalha por banda; aplicar direto num RGBA
        realçaria também o alpha e serrilharia a borda do recorte, então o
        alpha é separado, preservado e recolado.
        """
        from PIL import ImageFilter

        filtro = ImageFilter.UnsharpMask(
            radius=self.unsharp_raio,
            percent=int(round(self.unsharp_forca * 100)),
            threshold=3,
        )
        if imagem.mode != "RGBA":
            return imagem.filter(filtro)

        alpha = imagem.getchannel("A")
        realcada = imagem.convert("RGB").filter(filtro).convert("RGBA")
        realcada.putalpha(alpha)
        return realcada
