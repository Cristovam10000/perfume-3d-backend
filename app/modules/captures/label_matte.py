"""Separa o texto da label do fundo de vidro fotografado, gerando o alpha.

Motivacao: o recorte que sai do `LabelExtractor` (ou da marcacao `labelBox` do
app) e RGB opaco e contem o texto **mais o pedaco de vidro em volta**. Projetado
assim, esse fundo vira um retangulo de foto chapado colado no frasco — o defeito
visivel no job 3a3adbc8. O que se quer projetar sao so as letras.

Por que nao um limiar simples: medido no recorte real daquele job, o gradiente
de iluminacao da foto tem amplitude MAIOR que a diferenca entre texto e fundo.

    cantos   107-131      <- variacao so da iluminacao
    centro   136
    texto    p99=156      <- separacao texto/fundo ~24, gradiente ~29

Nenhum limiar global separa os dois. A saida e estimar o fundo com um blur
grande e subtrair: sobra o que e *localmente* mais claro que a vizinhanca, que e
exatamente a tinta. Depois um piso corta o grao do sensor, que sem ele vira uma
nuvem de pontinhos brancos espalhada pelo frasco.

Mesmo padrao Strategy do resto do modulo: ABC + bypass + implementacao real.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.label_matte")


class LabelMatte(ABC):
    """Contrato dos geradores de alpha da label."""

    @abstractmethod
    async def aplicar(self, entrada: Path, saida: Path) -> Path:
        """Grava em `saida` a label RGBA com o fundo transparente."""


class DisabledLabelMatte(LabelMatte):
    """Bypass: copia a imagem sem gerar alpha.

    Preserva o comportamento anterior (label opaca, com o retangulo) para quem
    quiser desligar o estagio sem mexer no resto do pipeline.
    """

    async def aplicar(self, entrada: Path, saida: Path) -> Path:
        import shutil

        if not entrada.exists():
            raise FileNotFoundError(f"Label de entrada nao encontrada: {entrada}")
        saida.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entrada, saida)
        return saida


class BackgroundSubtractionLabelMatte(LabelMatte):
    """Alpha por subtracao de fundo, para texto claro sobre vidro.

    Os defaults saem da calibracao no recorte real do job 3a3adbc8:

    - `raio_fundo=0.04` do lado maior. Precisa ser bem maior que a espessura da
      letra (senao o blur "acompanha" a letra e o residual some) e menor que a
      escala do gradiente de iluminacao.
    - `piso=6` e `ganho=13` sobre o residual em 0-255. Com piso 10 / ganho 22 o
      texto saia opaco em apenas 1,6% da area e sumia contra o vidro ao ser
      reduzido para o tamanho da label na tela; com estes, 5,2%.
    """

    def __init__(
        self,
        raio_fundo: float = 0.04,
        piso: float = 6.0,
        ganho: float = 13.0,
        forcar_branco: bool = True,
    ):
        if not 0.0 < raio_fundo < 1.0:
            raise ValueError("raio_fundo deve estar em (0, 1)")
        if piso < 0:
            raise ValueError("piso nao pode ser negativo")
        if ganho <= piso:
            raise ValueError("ganho precisa ser maior que piso")
        self.raio_fundo = raio_fundo
        self.piso = piso
        self.ganho = ganho
        self.forcar_branco = forcar_branco

    async def aplicar(self, entrada: Path, saida: Path) -> Path:
        return await asyncio.to_thread(self._aplicar_sync, entrada, saida)

    def _aplicar_sync(self, entrada: Path, saida: Path) -> Path:
        import numpy as np
        from PIL import Image, ImageFilter

        if not entrada.exists():
            raise FileNotFoundError(f"Label de entrada nao encontrada: {entrada}")
        saida.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(entrada) as arquivo:
            img = arquivo.convert("RGB")

        largura, altura = img.size
        raio = max(2.0, self.raio_fundo * max(largura, altura))

        cinza = img.convert("L")
        # Mediana antes do resto: mata grao sem comer a borda da letra, que e
        # muito mais espessa que o ruido.
        cinza = cinza.filter(ImageFilter.MedianFilter(size=3))
        fundo = cinza.filter(ImageFilter.GaussianBlur(radius=raio))

        residual = np.asarray(cinza, dtype=np.float32) - np.asarray(
            fundo, dtype=np.float32
        )
        alpha = np.clip(
            (residual - self.piso) / (self.ganho - self.piso), 0.0, 1.0
        )

        rgb = np.asarray(img, dtype=np.float32)
        if self.forcar_branco:
            # O pixel original e cinza-creme de baixissimo contraste. Mantido
            # como esta, o texto some contra o vidro no modelo; puxar para
            # branco onde ha tinta e o que o torna legivel.
            mistura = alpha[..., None]
            rgb = rgb * (1.0 - mistura) + 255.0 * mistura

        rgba = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
        Image.fromarray(rgba, mode="RGBA").save(saida, format="PNG")

        cobertura = float((alpha > 0.5).mean() * 100.0)
        _log.info(
            "Matte da label: %dx%d, raio=%.0fpx, %.2f%% de tinta",
            largura,
            altura,
            raio,
            cobertura,
        )
        if cobertura < 0.05:
            _log.warning(
                "Matte quase vazio (%.3f%%); a label pode sumir no modelo",
                cobertura,
            )
        return saida
