"""Extração e correção perspectiva da label frontal do frasco de perfume.

Recebe a foto original (RGB) e a máscara RGBA gerada pelo BackgroundRemover.
Localiza a região da label, aplica transformação de perspectiva (homografia) e
entrega a label como PNG plano — pronto para ser projetado sobre o GLB.

Mesmo padrão Strategy do restante do módulo: ABC + bypass + implementação
real trocável por configuração.

Implementações disponíveis:
- `DisabledLabelExtractor`: sempre retorna None (sem extração).
- `HomographyLabelExtractor`: detecção por região + warpPerspective via OpenCV.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.label_extractor")


@dataclass(frozen=True)
class ExtractedLabel:
    image_path: Path    # PNG da label com perspectiva corrigida
    confidence: float   # 0..1, score de quão "label" a região parece
    aspect_ratio: float # largura / altura da label extraída
    # Altura do centro da label na silhueta do frasco: 0.0 = topo, 1.0 = base.
    # O `LabelProjector` usa isso para posicionar o decal na altura certa; sem
    # essa informação ele cai no centroide do corpo, que fica abaixo da label
    # real na maioria dos frascos.
    vertical_position: float = 0.5


class LabelExtractor(ABC):
    """Contrato dos extratores de label."""

    @abstractmethod
    async def extract(
        self,
        image_path: Path,   # foto original (RGB)
        mask_path: Path,    # PNG RGBA do BackgroundRemover
        output_path: Path,
    ) -> ExtractedLabel | None:
        """Localiza e corrige a perspectiva da label frontal.

        Retorna None quando nenhuma região plausível de label for encontrada.
        """


class DisabledLabelExtractor(LabelExtractor):
    """Bypass: sempre retorna None. Use quando extração não é desejada."""

    async def extract(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
    ) -> ExtractedLabel | None:
        return None


class HomographyLabelExtractor(LabelExtractor):
    """Extrai a label frontal por **detecção de região** + correção de perspectiva.

    Por que região e não borda
    --------------------------
    A implementação anterior procurava quadriláteros nos contornos de um mapa de
    bordas Canny dilatado. Em foto real o Canny produz traços **fragmentados e
    abertos**, e `contourArea` de um traço mede a área do risco (~3 px de
    espessura), não a região que ele delimita. Medido nas 21 fotos reais dos 6
    jobs do projeto: **0 detecções**, com o maior candidato em 0,03%–1,0% da
    máscara contra um mínimo exigido de 5%.

    Os 12 testes unitários passavam porque usavam um retângulo branco perfeito
    sobre fundo preto (`cv2.rectangle(..., thickness=3)`), onde o Canny fecha o
    contorno e a área bate. O teste validava a premissa, não a realidade.

    Algoritmo atual
    ---------------
    1. Silhueta binária a partir do canal alpha da máscara.
    2. Recorte na bounding box do frasco.
    3. **Ensemble de binarizações** (Otsu claro/escuro + fechamentos
       morfológicos). Cada hipótese responde a um jeito de a label se destacar:
       placa clara sobre vidro escuro, texto claro sobre corpo escuro, etc. O
       fechamento une letras soltas num bloco.
    4. Cada região vira candidato; `_pontuar` combina área, proporção,
       centralização e retangularidade num score 0..1.
    5. Melhor score acima de `min_score` vence; senão devolve None.
    6. `minAreaRect` do contorno dá os 4 cantos (sempre 4, mesmo com contorno
       irregular) → `getPerspectiveTransform` → `warpPerspective`.

    Calibração e limites
    --------------------
    Medido nas fotos reais do projeto:

    - **La vivacité** (placa prateada retangular): detecção correta, score 0,78.
    - **ASAD** (texto dourado + medalhão): encontra o **medalhão**, não o texto.
      É um emblema real da marca, mas não é a label.
    - **Feeling Sexy** (texto em script diagonal): região parcial, score 0,67.
    - **GRAND** (texto impresso direto no vidro): nenhum candidato.

    O default `min_score=0.75` deixa passar apenas o caso de placa real. Isso é
    deliberado: projetar um recorte errado no GLB é pior do que não projetar
    nada. Frascos sem placa — texto impresso direto no vidro — não têm região
    para extrair, e devolver None neles é o comportamento correto.
    """

    # Faixa de área do candidato, em % da máscara do frasco. Placa de perfume
    # fica em torno de 8%; abaixo de 1,5% é ruído, acima de 45% é o corpo.
    _AREA_IDEAL_PCT = 8.0

    def __init__(
        self,
        min_area_ratio: float = 0.015,  # 1,5% da máscara
        max_area_ratio: float = 0.45,   # 45% (acima disso é o corpo do frasco)
        target_width: int = 1024,       # resolução horizontal do PNG de saída
        min_score: float = 0.75,        # abaixo disso, não projeta
    ):
        if not 0.0 < min_area_ratio < max_area_ratio <= 1.0:
            raise ValueError(
                "min_area_ratio e max_area_ratio devem satisfazer "
                "0 < min < max <= 1"
            )
        if not 0.0 <= min_score <= 1.0:
            raise ValueError(f"min_score deve estar em [0, 1]: {min_score}")
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.target_width = target_width
        self.min_score = min_score

    async def extract(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
    ) -> ExtractedLabel | None:
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
        if not mask_path.exists():
            raise FileNotFoundError(f"Máscara não encontrada: {mask_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(
            self._extract_sync, image_path, mask_path, output_path
        )

    # ------------------------------------------------------------------ sync

    def _extract_sync(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
    ) -> ExtractedLabel | None:
        # Imports lazy: módulo importa mesmo sem cv2/numpy instalados.
        import cv2
        import numpy as np

        imagem_rgb = cv2.imread(str(image_path))
        if imagem_rgb is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a imagem: {image_path}")

        mascara_rgba = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mascara_rgba is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a máscara: {mask_path}")

        canal_alpha = (
            mascara_rgba[:, :, 3]
            if mascara_rgba.ndim == 3 and mascara_rgba.shape[2] == 4
            else (mascara_rgba[:, :, 0] if mascara_rgba.ndim == 3 else mascara_rgba)
        )

        # Foto e máscara vêm do mesmo frame, mas o preprocessador pode ter
        # redimensionado uma delas. Sem alinhar as dimensões, os dois recortes
        # saem com shapes diferentes e o `bitwise_and` estoura.
        altura_img, largura_img = imagem_rgb.shape[:2]
        if canal_alpha.shape[:2] != (altura_img, largura_img):
            _log.info(
                "Máscara %s difere da foto %s; redimensionando a máscara",
                canal_alpha.shape[:2],
                (altura_img, largura_img),
            )
            canal_alpha = cv2.resize(
                canal_alpha, (largura_img, altura_img), interpolation=cv2.INTER_NEAREST
            )

        _, silhueta = cv2.threshold(canal_alpha, 127, 255, cv2.THRESH_BINARY)

        area_mascara = float(np.count_nonzero(silhueta))
        if area_mascara == 0:
            _log.warning("Máscara vazia — sem frasco detectado em %s", mask_path)
            return None

        x_bb, y_bb, w_bb, h_bb = cv2.boundingRect(cv2.findNonZero(silhueta))
        recorte = imagem_rgb[y_bb : y_bb + h_bb, x_bb : x_bb + w_bb]
        if recorte.size == 0:
            return None
        cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        silhueta_recorte = silhueta[y_bb : y_bb + h_bb, x_bb : x_bb + w_bb]

        melhor = self._melhor_candidato(
            cinza, silhueta_recorte, area_mascara=area_mascara, largura_frasco=w_bb
        )
        if melhor is None:
            _log.info("Nenhuma label plausível encontrada em %s", image_path)
            return None

        score, contorno = melhor

        # Altura relativa do centro da label dentro da silhueta do frasco.
        # Preservada para o projetor posicionar o decal na altura correta.
        _, y_c, _, h_c = cv2.boundingRect(contorno)
        posicao_vertical = min(max((y_c + h_c / 2.0) / max(h_bb, 1), 0.0), 1.0)

        # `minAreaRect` devolve sempre 4 cantos, mesmo com contorno irregular —
        # ao contrário de `approxPolyDP`, que só às vezes fecha em quadrilátero.
        cantos = cv2.boxPoints(cv2.minAreaRect(contorno)).astype(np.float32)
        cantos[:, 0] += x_bb
        cantos[:, 1] += y_bb
        cantos_ordenados = _ordenar_cantos(cantos)

        largura_label = float(
            max(
                np.linalg.norm(cantos_ordenados[1] - cantos_ordenados[0]),
                np.linalg.norm(cantos_ordenados[2] - cantos_ordenados[3]),
            )
        )
        altura_label = float(
            max(
                np.linalg.norm(cantos_ordenados[3] - cantos_ordenados[0]),
                np.linalg.norm(cantos_ordenados[2] - cantos_ordenados[1]),
            )
        )
        if altura_label <= 0 or largura_label <= 0:
            return None

        proporcao = largura_label / altura_label
        largura_alvo = self.target_width
        altura_alvo = max(int(round(largura_alvo / proporcao)), 1)

        destino = np.array(
            [
                [0, 0],
                [largura_alvo - 1, 0],
                [largura_alvo - 1, altura_alvo - 1],
                [0, altura_alvo - 1],
            ],
            dtype=np.float32,
        )

        matriz = cv2.getPerspectiveTransform(cantos_ordenados, destino)
        label_plana = cv2.warpPerspective(
            imagem_rgb, matriz, (largura_alvo, altura_alvo)
        )
        cv2.imwrite(str(output_path), label_plana)

        _log.info(
            "Label extraída: proporção=%.2f, score=%.3f, altura=%.2f, saída=%s",
            proporcao,
            score,
            posicao_vertical,
            output_path,
        )
        return ExtractedLabel(
            image_path=output_path,
            confidence=score,
            aspect_ratio=proporcao,
            vertical_position=posicao_vertical,
        )

    # -------------------------------------------------------------- detecção

    def _binarizacoes(self, cinza) -> dict[str, object]:
        """Hipóteses de "a label se destaca do corpo do frasco".

        Duas polaridades porque a label tanto pode ser clara sobre corpo escuro
        (placa prateada) quanto escura sobre corpo claro. Os fechamentos unem
        letras soltas num bloco — sem isso, texto impresso vira dezenas de
        regiões minúsculas em vez de uma região só.
        """
        import cv2

        saida: dict[str, object] = {}
        for nome, flag in (
            ("claro", cv2.THRESH_BINARY),
            ("escuro", cv2.THRESH_BINARY_INV),
        ):
            _, base = cv2.threshold(cinza, 0, 255, flag + cv2.THRESH_OTSU)
            saida[f"otsu_{nome}"] = base
            for k in (15, 31):
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
                saida[f"otsu_{nome}_close{k}"] = cv2.morphologyEx(
                    base, cv2.MORPH_CLOSE, kernel
                )
        return saida

    def _melhor_candidato(
        self, cinza, silhueta_recorte, *, area_mascara: float, largura_frasco: int
    ):
        """Percorre o ensemble e devolve (score, contorno) do melhor candidato."""
        import cv2

        melhor = None
        for binaria in self._binarizacoes(cinza).values():
            # Restringe ao interior do frasco: fundo removido não gera candidato.
            dentro = cv2.bitwise_and(binaria, silhueta_recorte)
            contornos, _ = cv2.findContours(
                dentro, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contorno in contornos:
                area = float(cv2.contourArea(contorno))
                if area <= 0:
                    continue
                x, y, w, h = cv2.boundingRect(contorno)
                if w == 0 or h == 0:
                    continue
                score = self._pontuar(
                    area_pct=100.0 * area / area_mascara,
                    proporcao=w / h,
                    desvio_centro=abs((x + w / 2.0) - largura_frasco / 2.0)
                    / max(largura_frasco, 1),
                    retangularidade=area / (w * h),
                )
                if score >= self.min_score and (melhor is None or score > melhor[0]):
                    melhor = (score, contorno)
        return melhor

    def _pontuar(
        self,
        *,
        area_pct: float,
        proporcao: float,
        desvio_centro: float,
        retangularidade: float,
    ) -> float:
        """Score 0..1 de quanto a região parece uma label de perfume.

        Zera fora dos limites duros; dentro deles, combina quatro sinais. A
        proporção ideal 2.0 reflete que labels de perfume são tipicamente mais
        largas que altas.
        """
        if not (self.min_area_ratio * 100 <= area_pct <= self.max_area_ratio * 100):
            return 0.0
        if not (0.4 <= proporcao <= 4.0):
            return 0.0
        if desvio_centro > 0.22:
            return 0.0
        if retangularidade < 0.55:
            return 0.0

        s_area = 1.0 - min(abs(area_pct - self._AREA_IDEAL_PCT) / 20.0, 1.0)
        s_prop = 1.0 - min(abs(proporcao - 2.0) / 2.0, 1.0)
        s_centro = 1.0 - desvio_centro / 0.22
        return 0.35 * s_area + 0.25 * s_prop + 0.15 * s_centro + 0.25 * retangularidade


def _ordenar_cantos(pontos):
    """Ordena 4 pontos como [TL, TR, BR, BL] usando soma e diferença de coordenadas.

    Soma mínima → TL; soma máxima → BR.
    Diferença mínima → TR; diferença máxima → BL.
    """
    import numpy as np

    soma = pontos.sum(axis=1)
    diff = np.diff(pontos, axis=1).ravel()

    cantos = np.zeros((4, 2), dtype=np.float32)
    cantos[0] = pontos[np.argmin(soma)]   # TL: menor soma (x+y)
    cantos[2] = pontos[np.argmax(soma)]   # BR: maior soma (x+y)
    cantos[1] = pontos[np.argmin(diff)]   # TR: menor diff (x-y)
    cantos[3] = pontos[np.argmax(diff)]   # BL: maior diff (x-y)
    return cantos
