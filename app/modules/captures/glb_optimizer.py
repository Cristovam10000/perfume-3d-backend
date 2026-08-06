"""Comprime o GLB final com Draco antes de entregar ao app.

O pipeline produzia GLBs de ate 77 MB, baixados pelo celular por Wi-Fi a cada
abertura do produto. ~90% do arquivo e malha, e a malha comprime muito bem:
medido em 5,5x no job `15ef21e9` (77,1 MB -> 13,9 MB) sem perda visivel.

Estrategia separada em vez de um flag nos scripts que ja exportam GLB
(`refine_ai_mesh`, `project_label`, `project_view_texture`): qual deles produz o
artefato final varia conforme os estagios opcionais que rodaram. Um estagio
proprio no fim da cadeia comprime uma vez so, sempre o arquivo certo.

`DisabledGlbOptimizer` existe para ambientes sem Blender e para desligar a
compressao via `.env` caso um cliente nao consiga decodificar Draco.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.glb_optimizer")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "optimize_glb.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)


@dataclass(frozen=True)
class GlbOptimizationInput:
    input_glb: Path
    output_glb: Path
    position_quantization: int = 14
    texcoord_quantization: int = 12


@dataclass(frozen=True)
class GlbOptimizationResult:
    output_glb: Path
    bytes_antes: int
    bytes_depois: int

    @property
    def fator(self) -> float:
        return self.bytes_antes / self.bytes_depois if self.bytes_depois else 0.0


class GlbOptimizationError(Exception):
    """Falha durante a compressao do GLB."""


class GlbOptimizer(ABC):
    @abstractmethod
    async def optimize(self, input: GlbOptimizationInput) -> GlbOptimizationResult: ...


class DisabledGlbOptimizer(GlbOptimizer):
    """Bypass: copia o GLB sem comprimir."""

    async def optimize(self, input: GlbOptimizationInput) -> GlbOptimizationResult:
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        tamanho = input.output_glb.stat().st_size
        return GlbOptimizationResult(
            output_glb=input.output_glb,
            bytes_antes=tamanho,
            bytes_depois=tamanho,
        )


class BlenderGlbOptimizer(GlbOptimizer):
    """Comprime com Draco via Blender headless."""

    def __init__(
        self,
        blender_executable: Path | None = None,
        script_path: Path | None = None,
        timeout_seconds: float = 300.0,
    ):
        self.blender_executable = (
            Path(blender_executable)
            if blender_executable is not None
            else _DEFAULT_BLENDER_EXECUTABLE
        )
        self.script_path = Path(script_path) if script_path else _DEFAULT_SCRIPT_PATH
        self.timeout_seconds = timeout_seconds

    async def optimize(self, input: GlbOptimizationInput) -> GlbOptimizationResult:
        self._assert_runtime_assets(input)
        bytes_antes = input.input_glb.stat().st_size

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input", str(input.input_glb),
            "--output", str(input.output_glb),
            "--position-quantization", str(input.position_quantization),
            "--texcoord-quantization", str(input.texcoord_quantization),
        ]

        returncode, _stdout, stderr = await self._run_blender(args)
        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise GlbOptimizationError(
                f"Blender retornou {returncode} ao comprimir GLB: {tail}"
            )
        if not input.output_glb.exists():
            raise GlbOptimizationError(
                f"Blender concluiu sem erros mas GLB de saida nao foi criado: "
                f"{input.output_glb}"
            )

        bytes_depois = input.output_glb.stat().st_size
        resultado = GlbOptimizationResult(
            output_glb=input.output_glb,
            bytes_antes=bytes_antes,
            bytes_depois=bytes_depois,
        )
        _log.info(
            "GLB comprimido: %.1f MB -> %.1f MB (%.1fx)",
            bytes_antes / 1e6,
            bytes_depois / 1e6,
            resultado.fator,
        )
        return resultado

    def _assert_runtime_assets(self, input: GlbOptimizationInput) -> None:
        if not self.blender_executable.exists():
            raise GlbOptimizationError(
                f"Executavel do Blender nao encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise GlbOptimizationError(
                f"Script do Blender nao encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise GlbOptimizationError(
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
            raise GlbOptimizationError(
                f"Blender excedeu timeout de {self.timeout_seconds}s ao comprimir"
            ) from None
        return completed.returncode, completed.stdout or b"", completed.stderr or b""
