"""Remoção de fundo das fotos do frasco de perfume.

Prepara a imagem para o pipeline 3D: retira o fundo e entrega o frasco
como PNG RGBA (canal alpha = máscara do frasco). Etapa anterior à
extração de label e à reconstrução 3D.

Mesmo padrão Strategy do `Classifier` e do `ColorDetector`: ABC +
bypass desativado + implementação real trocável por configuração.

Implementações disponíveis:
- `DisabledBackgroundRemover`: copia o arquivo de entrada sem alterações.
- `RembgBackgroundRemover`: usa rembg com modelo isnet-general-use.
"""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.background_remover")


class BackgroundRemover(ABC):
    """Contrato dos removedores de fundo."""

    @abstractmethod
    async def remove(self, image_path: Path, output_path: Path) -> Path:
        """Remove o fundo da imagem e salva PNG RGBA em output_path.

        Retorna output_path. O canal alpha representa a máscara do frasco:
        255 = frasco, 0 = fundo removido.
        """


class DisabledBackgroundRemover(BackgroundRemover):
    """Bypass: copia o arquivo de entrada sem remover o fundo.

    Útil quando rembg não está instalado, em testes, ou para desenvolvimento
    sem GPU. O arquivo copiado pode não ser RGBA — fases seguintes devem
    tolerar isso.
    """

    async def remove(self, image_path: Path, output_path: Path) -> Path:
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, output_path)
        _log.debug("BackgroundRemover desativado: copiou %s → %s", image_path, output_path)
        return output_path


class RembgBackgroundRemover(BackgroundRemover):
    """Remove fundo usando rembg com o modelo isnet-general-use.

    O modelo isnet-general-use oferece o melhor equilíbrio entre qualidade
    e velocidade para fotos de produtos (frascos de perfume incluídos).

    A sessão rembg é cara de inicializar (~2GB de download na primeira vez)
    e é cacheada na instância para reúso entre chamadas. A inferência roda
    em asyncio.to_thread para não bloquear o event loop do FastAPI.
    """

    def __init__(self, model_name: str = "isnet-general-use"):
        self.model_name = model_name
        self._sessao: object | None = None

    async def remove(self, image_path: Path, output_path: Path) -> Path:
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(self._remove_sync, image_path, output_path)

    # ------------------------------------------------------------------ sync

    def _remove_sync(self, image_path: Path, output_path: Path) -> Path:
        """Executa remoção de fundo em thread — não bloqueia o event loop."""
        self._garantir_sessao()

        # Imports lazy: o módulo importa sem rembg/Pillow instalados.
        from PIL import Image
        import rembg

        _log.info("Removendo fundo de %s com modelo '%s'", image_path, self.model_name)

        with Image.open(image_path) as imagem_entrada:
            imagem_rgba = rembg.remove(imagem_entrada, session=self._sessao)

        # Garante que a saída seja sempre RGBA, independente do formato de entrada.
        if imagem_rgba.mode != "RGBA":
            imagem_rgba = imagem_rgba.convert("RGBA")

        imagem_rgba.save(output_path, format="PNG")
        _log.info("Máscara salva em %s", output_path)
        return output_path

    def _garantir_sessao(self) -> None:
        """Carrega a sessão rembg na primeira chamada e reutiliza nas demais."""
        if self._sessao is not None:
            return
        import rembg

        _log.info("Carregando sessão rembg (modelo '%s')...", self.model_name)
        self._sessao = rembg.new_session(self.model_name)
