"""Pré-processamento de fotos cruas de smartphone antes do pipeline 3D.

Corrige aberrações comuns (orientação EXIF, tinte de iluminação, subexposição,
borrão leve) usando técnicas clássicas de visão computacional. O resultado
alimenta o `BackgroundRemover` e, em seguida, o `Hunyuan3DProcessor` com fotos
mais consistentes — sem dependência de modelos treinados.

Mesmo padrão Strategy do restante do módulo: ABC + bypass desativado +
implementação real trocável por configuração.

Implementações disponíveis:
- `DisabledImagePreprocessor`: copia o arquivo de entrada sem alterações.
- `StandardImagePreprocessor`: pipeline OpenCV/PIL clássico (gray-world WB,
  CLAHE no L do LAB, unsharp condicional, redimensionamento).
"""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.image_preprocessor")


_EXTENSOES_JPEG = {".jpg", ".jpeg"}


class ImagePreprocessor(ABC):
    """Contrato dos pré-processadores de imagem."""

    @abstractmethod
    async def preprocess(self, input_path: Path, output_path: Path) -> Path:
        """Aplica o pré-processamento e salva em output_path. Retorna output_path."""


class DisabledImagePreprocessor(ImagePreprocessor):
    """Bypass: copia o arquivo de entrada sem aplicar correções.

    Útil em testes ou quando OpenCV/Pillow não estão instalados.
    """

    async def preprocess(self, input_path: Path, output_path: Path) -> Path:
        if not input_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {input_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        _log.debug(
            "ImagePreprocessor desativado: copiou %s → %s", input_path, output_path
        )
        return output_path


class StandardImagePreprocessor(ImagePreprocessor):
    """Pré-processamento clássico para fotos de smartphone.

    Aplica em ordem:

    1. **EXIF auto-rotate** via `PIL.ImageOps.exif_transpose` (corrige fotos
       em retrato/paisagem capturadas com sensores rotacionados).
    2. **White balance** por gray-world: cada canal é multiplicado por
       (média_global / média_canal). Heurística simples, robusta em luz mista.
    3. **Exposure correction** via CLAHE no canal L do LAB. CLAHE diretamente
       no RGB satura cores; trabalhar em LAB preserva matiz.
    4. **Detecção de motion blur** via Laplacian variance. Se a variância for
       *menor* que `sharpen_threshold`, aplica unsharp mask. Foto já nítida
       não recebe sharpening adicional (evita ruído amplificado).
    5. **Resize** para no máximo `max_resolution` no maior lado, mantendo o
       aspect ratio. Hunyuan3D-2mv não consome mais do que isso.
    6. **Save**: PNG sem compressão para `.png`, JPEG quality 95 para o resto.

    Documentação científica: este é pré-processamento baseado em técnicas
    clássicas de visão computacional, escolhidas pela robustez e ausência de
    dependências de modelos treinados. Não pretende competir com AWB neural ou
    deblur neural — é a camada determinística que torna fotos de smartphone
    "boas o suficiente" para os passos seguintes.
    """

    def __init__(
        self,
        white_balance: bool = True,
        clahe_clip_limit: float = 2.0,
        sharpen_threshold: float = 100.0,
        max_resolution: int = 2048,
    ):
        if clahe_clip_limit <= 0:
            raise ValueError("clahe_clip_limit deve ser > 0")
        if sharpen_threshold < 0:
            raise ValueError("sharpen_threshold deve ser >= 0")
        if max_resolution <= 0:
            raise ValueError("max_resolution deve ser > 0")
        self.white_balance = white_balance
        self.clahe_clip_limit = clahe_clip_limit
        self.sharpen_threshold = sharpen_threshold
        self.max_resolution = max_resolution

    async def preprocess(self, input_path: Path, output_path: Path) -> Path:
        if not input_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {input_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(self._preprocess_sync, input_path, output_path)

    # ------------------------------------------------------------------ sync

    def _preprocess_sync(self, input_path: Path, output_path: Path) -> Path:
        """Executa o pipeline de pré-processamento em thread."""
        # Imports lazy: o módulo importa sem cv2/PIL/numpy instalados.
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        _log.info("Pré-processando %s", input_path)

        # 1. EXIF auto-rotate (PIL é mais confiável que cv2 para isso).
        with Image.open(input_path) as imagem_pil:
            imagem_corrigida = ImageOps.exif_transpose(imagem_pil)
            if imagem_corrigida.mode != "RGB":
                imagem_corrigida = imagem_corrigida.convert("RGB")
            # Converte para BGR (convenção do cv2) para o resto do pipeline.
            arr_rgb = np.array(imagem_corrigida)
        imagem_bgr = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)

        # 2. Gray-world white balance.
        if self.white_balance:
            imagem_bgr = self._aplicar_gray_world(imagem_bgr)

        # 3. CLAHE no canal L do LAB.
        imagem_bgr = self._aplicar_clahe_lab(imagem_bgr)

        # 4. Sharpening condicional (apenas se a foto estiver borrada).
        imagem_bgr = self._sharpen_se_borrada(imagem_bgr)

        # 5. Redimensiona mantendo aspect ratio.
        imagem_bgr = self._redimensionar(imagem_bgr)

        # 6. Salva no formato derivado da extensão.
        self._salvar(imagem_bgr, output_path)
        _log.info("Pré-processamento salvo em %s", output_path)
        return output_path

    # ------------------------------------------------------------------ etapas

    def _aplicar_gray_world(self, imagem_bgr):
        """White balance por gray-world: normaliza cada canal pela média global.

        A premissa é que, na média, a cena é cinza neutro. Tinte amarelo, azul ou
        verde decorrente da iluminação aparece como média de canal desbalanceada;
        compensa-se multiplicando cada canal pela razão média_global/média_canal.
        """
        import numpy as np

        # float32 evita overflow ao escalar canais.
        flutuante = imagem_bgr.astype(np.float32)
        medias = flutuante.reshape(-1, 3).mean(axis=0)
        media_global = medias.mean()
        if media_global <= 0:
            return imagem_bgr  # imagem completamente preta

        # Evita divisão por zero em canais quase pretos.
        fatores = np.where(medias > 1e-3, media_global / medias, 1.0).astype(np.float32)
        flutuante *= fatores
        balanceada = np.clip(flutuante, 0.0, 255.0).astype(imagem_bgr.dtype)
        return balanceada

    def _aplicar_clahe_lab(self, imagem_bgr):
        """Aplica CLAHE no canal L do espaço LAB e remonta a imagem."""
        import cv2

        lab = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2LAB)
        canal_l, canal_a, canal_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=self.clahe_clip_limit, tileGridSize=(8, 8))
        canal_l_corrigido = clahe.apply(canal_l)
        lab_corrigida = cv2.merge((canal_l_corrigido, canal_a, canal_b))
        return cv2.cvtColor(lab_corrigida, cv2.COLOR_LAB2BGR)

    def _sharpen_se_borrada(self, imagem_bgr):
        """Aplica unsharp mask só se a foto parecer borrada (Laplacian < limiar)."""
        import cv2

        cinza = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2GRAY)
        variancia = cv2.Laplacian(cinza, cv2.CV_64F).var()
        if variancia >= self.sharpen_threshold:
            _log.debug(
                "Imagem nítida (Laplacian=%.1f >= %.1f) — sem sharpening",
                variancia, self.sharpen_threshold,
            )
            return imagem_bgr

        _log.info(
            "Foto borrada (Laplacian=%.1f < %.1f) — aplicando unsharp mask",
            variancia, self.sharpen_threshold,
        )
        borrada = cv2.GaussianBlur(imagem_bgr, (0, 0), sigmaX=1.5)
        nitida = cv2.addWeighted(imagem_bgr, 1.5, borrada, -0.5, 0)
        return nitida

    def _redimensionar(self, imagem_bgr):
        """Reduz a maior dimensão para `max_resolution`, preservando proporção."""
        import cv2

        altura, largura = imagem_bgr.shape[:2]
        maior_lado = max(altura, largura)
        if maior_lado <= self.max_resolution:
            return imagem_bgr

        fator = self.max_resolution / float(maior_lado)
        nova_largura = int(round(largura * fator))
        nova_altura = int(round(altura * fator))
        return cv2.resize(
            imagem_bgr,
            (nova_largura, nova_altura),
            interpolation=cv2.INTER_AREA,
        )

    def _salvar(self, imagem_bgr, output_path: Path) -> None:
        """Escolhe formato/qualidade pela extensão do path de saída."""
        import cv2

        sufixo = output_path.suffix.lower()
        if sufixo == ".png":
            cv2.imwrite(str(output_path), imagem_bgr)
        elif sufixo in _EXTENSOES_JPEG:
            cv2.imwrite(str(output_path), imagem_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        else:
            # Para extensões desconhecidas, deixa o cv2 inferir o codec.
            cv2.imwrite(str(output_path), imagem_bgr)
