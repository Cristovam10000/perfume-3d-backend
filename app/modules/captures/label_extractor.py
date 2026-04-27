"""Extração e correção perspectiva da label frontal do frasco de perfume.

Recebe a foto original (RGB) e a máscara RGBA gerada pelo BackgroundRemover.
Localiza a região retangular da label, aplica transformação de perspectiva
(homografia) e entrega a label como PNG plano — pronto para ser projetado
sobre o template 3D.

Mesmo padrão Strategy do restante do módulo: ABC + bypass + implementação
real trocável por configuração.

Implementações disponíveis:
- `DisabledLabelExtractor`: sempre retorna None (sem extração).
- `HomographyLabelExtractor`: detecção de contorno + warpPerspective via OpenCV.
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
    confidence: float   # 0..1, qualidade da extração (área contorno / área máscara)
    aspect_ratio: float # largura / altura da label extraída


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
    """Extrai a label frontal via detecção de contorno e transformação de perspectiva.

    Algoritmo:
    1. Carrega a máscara, limiariza o canal alpha para obter a silhueta binária.
    2. Dentro da bounding box do frasco, aplica Canny na imagem RGB original.
    3. Encontra contornos quadrilaterais (approxPolyDP com 4 vértices).
    4. Filtra por área (entre min_area_ratio e max_area_ratio da máscara),
       proporção (0.3–3.0) e posição horizontal (centrado no frasco).
    5. Escolhe o maior contorno válido. Se nenhum → retorna None.
    6. Ordena os 4 cantos (TL, TR, BR, BL) via soma/diferença das coordenadas.
    7. Calcula retângulo alvo: target_width × (target_width / aspect_ratio).
    8. getPerspectiveTransform + warpPerspective para achatar a label.
    9. Salva como PNG e retorna ExtractedLabel.
    """

    def __init__(
        self,
        min_area_ratio: float = 0.05,  # contorno deve ter >5% da área da máscara
        max_area_ratio: float = 0.60,  # e <60% (senão é o frasco inteiro)
        target_width: int = 1024,      # resolução horizontal do PNG de saída
    ):
        if not 0.0 < min_area_ratio < max_area_ratio <= 1.0:
            raise ValueError(
                "min_area_ratio e max_area_ratio devem satisfazer "
                "0 < min < max <= 1"
            )
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.target_width = target_width

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
        """Executa detecção e correção de perspectiva em thread."""
        # Imports lazy: módulo importa mesmo sem cv2/numpy instalados.
        import cv2
        import numpy as np

        imagem_rgb = cv2.imread(str(image_path))
        if imagem_rgb is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a imagem: {image_path}")

        mascara_rgba = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mascara_rgba is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a máscara: {mask_path}")

        # Canal alpha → silhueta binária do frasco.
        canal_alpha = mascara_rgba[:, :, 3] if mascara_rgba.shape[2] == 4 else mascara_rgba[:, :, 0]
        _, silhueta = cv2.threshold(canal_alpha, 127, 255, cv2.THRESH_BINARY)

        area_mascara = float(np.count_nonzero(silhueta))
        if area_mascara == 0:
            _log.warning("Máscara vazia — sem frasco detectado em %s", mask_path)
            return None

        # Bounding box do frasco para restringir a busca de bordas.
        coords = cv2.findNonZero(silhueta)
        x_bb, y_bb, w_bb, h_bb = cv2.boundingRect(coords)

        # Recorte da imagem original dentro da bounding box do frasco.
        recorte_rgb = imagem_rgb[y_bb : y_bb + h_bb, x_bb : x_bb + w_bb]
        recorte_cinza = cv2.cvtColor(recorte_rgb, cv2.COLOR_BGR2GRAY)

        # Detecção de bordas Canny para realçar a label.
        bordas = cv2.Canny(recorte_cinza, threshold1=50, threshold2=150)

        # Dilatação leve para fechar lacunas nas bordas da label.
        kernel = np.ones((3, 3), np.uint8)
        bordas = cv2.dilate(bordas, kernel, iterations=1)

        contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidato = self._selecionar_candidato(
            contornos,
            area_mascara=area_mascara,
            largura_frasco=w_bb,
            offset_x=x_bb,
            offset_y=y_bb,
        )

        if candidato is None:
            _log.info("Nenhuma label plausível encontrada em %s", image_path)
            return None

        contorno_label, area_contorno = candidato
        # Converte para float32 exigido por getPerspectiveTransform.
        pontos = contorno_label.reshape(4, 2).astype(np.float32)
        cantos_ordenados = _ordenar_cantos(pontos)

        # Dimensões do retângulo de saída.
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

        if altura_label == 0:
            return None

        proporcao = largura_label / altura_label
        altura_alvo = int(round(self.target_width / proporcao))
        largura_alvo = self.target_width

        destino = np.array(
            [
                [0, 0],
                [largura_alvo - 1, 0],
                [largura_alvo - 1, altura_alvo - 1],
                [0, altura_alvo - 1],
            ],
            dtype=np.float32,
        )

        # Transformação de perspectiva para achatar a label.
        matriz = cv2.getPerspectiveTransform(cantos_ordenados, destino)
        label_plana = cv2.warpPerspective(imagem_rgb, matriz, (largura_alvo, altura_alvo))

        cv2.imwrite(str(output_path), label_plana)

        confianca = min(1.0, area_contorno / area_mascara)
        _log.info(
            "Label extraída: proporção=%.2f, confiança=%.2f, saída=%s",
            proporcao,
            confianca,
            output_path,
        )
        return ExtractedLabel(
            image_path=output_path,
            confidence=confianca,
            aspect_ratio=proporcao,
        )

    def _selecionar_candidato(
        self,
        contornos: list,
        *,
        area_mascara: float,
        largura_frasco: int,
        offset_x: int,
        offset_y: int,
    ):
        """Filtra e escolhe o melhor contorno quadrilateral candidato a label.

        Retorna (contorno, area) ou None se nenhum candidato passar os filtros.
        """
        import cv2

        area_min = self.min_area_ratio * area_mascara
        area_max = self.max_area_ratio * area_mascara
        centro_frasco_x = offset_x + largura_frasco / 2.0

        melhor = None
        maior_area = 0.0

        for contorno in contornos:
            perimetro = cv2.arcLength(contorno, closed=True)
            # Margem de 5% para tolerar leve distorção de perspectiva.
            aproximacao = cv2.approxPolyDP(contorno, epsilon=0.05 * perimetro, closed=True)

            if len(aproximacao) != 4:
                continue

            area = float(cv2.contourArea(aproximacao))
            if not area_min <= area <= area_max:
                continue

            # Calcula proporção a partir do rect envolvente (mais estável que
            # as dimensões reais do quadrilátero sob perspectiva severa).
            x_r, y_r, w_r, h_r = cv2.boundingRect(aproximacao)
            if h_r == 0:
                continue
            proporcao = w_r / h_r
            if not 0.3 <= proporcao <= 3.0:
                continue

            # A label deve estar horizontalmente centrada no frasco (±35%).
            centro_contorno_x = offset_x + x_r + w_r / 2.0
            desvio_relativo = abs(centro_contorno_x - centro_frasco_x) / max(largura_frasco, 1)
            if desvio_relativo > 0.35:
                continue

            # Translada o contorno de volta para coordenadas da imagem completa.
            contorno_global = aproximacao.copy()
            contorno_global[:, :, 0] += offset_x
            contorno_global[:, :, 1] += offset_y

            if area > maior_area:
                maior_area = area
                melhor = (contorno_global, area)

        return melhor


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
