"""Renderiza o PNG de vitrine do modelo, exibido no card do produto.

A coluna `modelos_3d_produto.caminho_imagem_preview` existia desde o schema
original e nunca era preenchida: o `/sales` a devolvia como `previewImg`, o app
ja a lia, e ela era sempre nula — o card caia num gradiente generico. Faltava
justamente quem gerasse a imagem.

O preview e **opcional por contrato**: falhar aqui nao pode derrubar um job cujo
GLB ficou pronto. O pipeline degrada e o card volta ao gradiente, como era antes.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.preview_renderer")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "render_preview.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)


@dataclass(frozen=True)
class PreviewRenderInput:
    input_glb: Path
    output_png: Path
    resolution: int = 512


@dataclass(frozen=True)
class PreviewRenderResult:
    output_png: Path


class PreviewRenderError(Exception):
    """Falha ao renderizar o preview."""


class PreviewRenderer(ABC):
    @abstractmethod
    async def render(self, input: PreviewRenderInput) -> PreviewRenderResult: ...


class DisabledPreviewRenderer(PreviewRenderer):
    """Bypass: nao renderiza nada.

    Diferente dos outros `Disabled*` do modulo, este nao copia um arquivo de
    entrada — nao ha o que copiar. Sinaliza a ausencia com a excecao do modulo,
    que o pipeline ja trata como degradacao.
    """

    async def render(self, input: PreviewRenderInput) -> PreviewRenderResult:
        raise PreviewRenderError("Renderizacao de preview desabilitada")


class BlenderPreviewRenderer(PreviewRenderer):
    """Renderiza via Blender headless em EEVEE."""

    def __init__(
        self,
        blender_executable: Path | None = None,
        script_path: Path | None = None,
        timeout_seconds: float = 180.0,
    ):
        self.blender_executable = (
            Path(blender_executable)
            if blender_executable is not None
            else _DEFAULT_BLENDER_EXECUTABLE
        )
        self.script_path = Path(script_path) if script_path else _DEFAULT_SCRIPT_PATH
        self.timeout_seconds = timeout_seconds

    async def render(self, input: PreviewRenderInput) -> PreviewRenderResult:
        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input", str(input.input_glb),
            "--output", str(input.output_png),
            "--resolution", str(input.resolution),
        ]

        returncode, _stdout, stderr = await self._run_blender(args)
        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise PreviewRenderError(
                f"Blender retornou {returncode} ao renderizar preview: {tail}"
            )
        if not input.output_png.exists():
            raise PreviewRenderError(
                f"Blender concluiu sem erros mas PNG nao foi criado: {input.output_png}"
            )

        _log.info("Preview renderizado: %s", input.output_png)
        return PreviewRenderResult(output_png=input.output_png)

    def _assert_runtime_assets(self, input: PreviewRenderInput) -> None:
        if not self.blender_executable.exists():
            raise PreviewRenderError(
                f"Executavel do Blender nao encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise PreviewRenderError(
                f"Script do Blender nao encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise PreviewRenderError(
                f"GLB de entrada nao encontrado: {input.input_glb}"
            )

    async def _run_blender(self, args: list[str]) -> tuple[int, bytes, bytes]:
        return await asyncio.to_thread(self._run_blender_sync, args)

    def _run_blender_sync(self, args: list[str]) -> tuple[int, bytes, bytes]:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise PreviewRenderError(
                f"Blender excedeu timeout de {self.timeout_seconds}s no preview"
            ) from None
        return completed.returncode, completed.stdout or b"", completed.stderr or b""
