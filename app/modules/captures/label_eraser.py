"""Apaga a label da foto de referencia ANTES de ela ir para o gerador 3D.

Motivacao — o defeito do rotulo fantasma:

O pipeline de textura do Hunyuan aceita **uma** imagem de referencia e sintetiza
as demais vistas a partir dela. Como consequencia, o texto da label aparece
pintado na malha, espalhado por varias ilhas do atlas de UV e deslocado do lugar
real. Depois o pipeline assa a label verdadeira na posicao certa, e o frasco
termina com o rotulo DUAS vezes: o inventado e o real.

Tentou-se remover o texto ja pintado, direto no atlas 2048x2048, e nao fecha:
mistura com blur nao apaga a letra (sobrevive ate raio 60, empapando 37% da
imagem), difusao em numpy deixa contorno fantasma ou chapa a regiao, e ate com
`cv2.inpaint` restrito as faces era preciso reescrever ~26% da textura, o que
trocava o fantasma por salpico. Ver docs/09e.

A saida e nao deixar o texto ser pintado. Apagar a label de UMA foto 2D, antes
da geracao, e um problema pequeno e bem posto — e o resultado foi medido: com a
frontal limpa, o atlas gerado sai **sem texto nenhum**.

A regiao vem do pipeline, que a resolve antes do gerador: do `labelBox` do app
quando ele marca, ou do `HomographyLabelExtractor` quando nao. Sem regiao o
estagio nao roda e o comportamento antigo (com fantasma) e preservado — melhor
que adivinhar e apagar um pedaco legitimo do frasco.

Mesmo padrao Strategy do resto do modulo: ABC + bypass + implementacao real.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.label_eraser")


class LabelEraser(ABC):
    """Contrato dos apagadores de label na foto de referencia."""

    @abstractmethod
    async def apagar(
        self, entrada: Path, saida: Path, caixa_px: tuple[int, int, int, int]
    ) -> Path | None:
        """Grava em `saida` a foto sem a label. `None` quando nao houve o que fazer.

        `caixa_px` e (x, y, w, h) em pixels **da propria `entrada`**. Vem em
        pixels, e nao normalizada, porque quem a resolve e o pipeline — ora a
        partir do `labelBox` do app, ora do detector — e os dois ja trabalham
        nesse espaco. Converter para normalizado e de volta so introduziria
        arredondamento.
        """


class DisabledLabelEraser(LabelEraser):
    """Bypass: nao apaga nada. O gerador volta a pintar o rotulo fantasma."""

    async def apagar(
        self, entrada: Path, saida: Path, caixa_px: tuple[int, int, int, int]
    ) -> Path | None:
        return None


class InpaintLabelEraser(LabelEraser):
    """Apaga o texto da label por inpainting, dentro da caixa marcada.

    Detecta o texto pelo residual (o que e localmente mais claro que a
    vizinhanca) e reconstroi com `cv2.INPAINT_TELEA`, que propaga estrutura ao
    longo das isofotas — diferente de um borrao, que so atenua.

    Defaults calibrados no job 3a3adbc8 (`Hinode Spot for her`, texto gravado em
    vidro fosco), medindo a fracao da caixa afetada:

    - `piso=20` deixava marcas visiveis do texto;
    - `piso=12` apagava, mas achatava 38% da caixa e comia o grao do vidro;
    - `piso=16` apaga o texto preservando o grao, com ~20% da caixa.

    A margem existe porque o texto costuma passar um pouco da caixa marcada a
    mao. Ela e proporcional a caixa, e nao absoluta, para valer em qualquer
    resolucao de foto.
    """

    def __init__(
        self,
        piso: float = 16.0,
        raio_fundo: float = 14.0,
        dilatacao: int = 4,
        margem: float = 0.18,
    ):
        if piso <= 0:
            raise ValueError("piso deve ser positivo")
        if raio_fundo <= 0:
            raise ValueError("raio_fundo deve ser positivo")
        if dilatacao < 0:
            raise ValueError("dilatacao nao pode ser negativa")
        if not 0.0 <= margem < 1.0:
            raise ValueError("margem deve estar em [0, 1)")
        self.piso = piso
        self.raio_fundo = raio_fundo
        self.dilatacao = dilatacao
        self.margem = margem

    async def apagar(
        self, entrada: Path, saida: Path, caixa_px: tuple[int, int, int, int]
    ) -> Path | None:
        return await asyncio.to_thread(self._apagar_sync, entrada, saida, caixa_px)

    def _apagar_sync(
        self, entrada: Path, saida: Path, caixa_px: tuple[int, int, int, int]
    ) -> Path | None:
        import cv2
        import numpy as np
        from PIL import Image, ImageFilter

        if not entrada.exists():
            raise FileNotFoundError(f"Foto de referencia nao encontrada: {entrada}")

        try:
            x, y, w, h = (int(v) for v in caixa_px)
        except (TypeError, ValueError):
            _log.warning("caixa_px malformada: %r; foto segue intacta", caixa_px)
            return None

        with Image.open(entrada) as arquivo:
            original = arquivo.convert("RGBA")
        largura, altura = original.size
        rgb = original.convert("RGB")

        # Convencao de `_recortar_label_marcada_sync` e do extractor: (x, y, w,
        # h) em pixels do quadro inteiro, com y crescendo para baixo.
        mx, my = w * self.margem, h * self.margem
        x0 = max(int(round(x - mx)), 0)
        y0 = max(int(round(y - my)), 0)
        x1 = min(int(round(x + w + mx)), largura)
        y1 = min(int(round(y + h + my)), altura)
        if x1 - x0 < 4 or y1 - y0 < 4:
            _log.warning("Caixa da label degenerada: %r; foto segue intacta", caixa_px)
            return None

        cinza = rgb.convert("L")
        fundo = cinza.filter(ImageFilter.GaussianBlur(radius=self.raio_fundo))
        residual = np.asarray(cinza, dtype=np.float32) - np.asarray(
            fundo, dtype=np.float32
        )

        regiao = np.zeros(residual.shape, dtype=bool)
        regiao[y0:y1, x0:x1] = True
        mascara = ((residual > self.piso) & regiao).astype(np.uint8) * 255
        if self.dilatacao > 0:
            lado = self.dilatacao * 2 + 1
            mascara = cv2.dilate(
                mascara, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado))
            )
            # A dilatacao nao pode vazar da caixa: fora dela esta o frasco que
            # deve ser preservado.
            mascara = mascara * regiao.astype(np.uint8)

        pct = 100.0 * float((mascara[y0:y1, x0:x1] > 0).mean())
        if not (mascara > 0).any():
            _log.info("Nenhum texto detectado na caixa da label; foto segue intacta")
            return None

        limpo = cv2.inpaint(
            cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR),
            mascara,
            8,
            cv2.INPAINT_TELEA,
        )
        resultado = Image.fromarray(
            cv2.cvtColor(limpo, cv2.COLOR_BGR2RGB)
        ).convert("RGBA")
        # O alpha e o recorte do fundo feito pelo BackgroundRemover; o inpaint
        # trabalha so no RGB e nao pode desfazer a segmentacao.
        resultado.putalpha(original.getchannel("A"))

        saida.parent.mkdir(parents=True, exist_ok=True)
        resultado.save(saida, format="PNG")
        _log.info(
            "Label apagada da referencia: %.1f%% da caixa (piso=%.0f) -> %s",
            pct,
            self.piso,
            saida.name,
        )
        return saida
