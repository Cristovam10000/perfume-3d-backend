"""Projeta uma foto real do frasco nas faces do GLB que aquela foto enxerga.

Dois eixos, dois problemas distintos do gerador:

- `AXIS_TOP` (`z_pos`) — o Hunyuan3D-2mv reconstroi a partir de 4 vistas
  cardeais e nenhuma delas enxerga a tampa; ela sai como disco liso.
- `AXIS_BACK` (`y_pos`) — o Hunyuan gera a *geometria* com as 4 vistas mas a
  *textura* com UMA. O pipeline de paint aceita uma unica imagem de referencia
  e sintetiza as demais vistas a partir dela, entao o verso do frasco sai
  inventado (tipicamente uma copia da frente). Ver docs/16.

Nos dois casos a foto correta existe e so nao estava sendo usada. A projecao
troca o palpite do gerador pelo pixel medido.
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

_log = get_logger("captures.view_texture_projector")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "project_view_texture.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)

# Eixos aceitos pelo script Blender. A convencao "frente = -Y" vem de
# FRONT_AXES em project_label.py, logo o verso do frasco e +Y.
AXIS_TOP = "z_pos"
AXIS_BACK = "y_pos"
VALID_AXES: frozenset[str] = frozenset({AXIS_TOP, AXIS_BACK})

_ROTULOS = {AXIS_TOP: "topo", AXIS_BACK: "costas"}


@dataclass(frozen=True)
class ViewTextureProjectionInput:
    input_glb: Path
    photo: Path
    output_glb: Path
    axis: str = AXIS_TOP
    cosine_threshold: float = 0.45


@dataclass(frozen=True)
class ViewTextureProjectionResult:
    output_glb: Path


class ViewTextureProjectionError(Exception):
    """Falha durante a projeção da textura."""


class ViewTextureProjector(ABC):
    @abstractmethod
    async def project(
        self, input: ViewTextureProjectionInput
    ) -> ViewTextureProjectionResult: ...


class DisabledViewTextureProjector(ViewTextureProjector):
    """Bypass: copia o GLB de entrada sem modificar."""

    async def project(
        self, input: ViewTextureProjectionInput
    ) -> ViewTextureProjectionResult:
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return ViewTextureProjectionResult(output_glb=input.output_glb)


class BlenderViewTextureProjector(ViewTextureProjector):
    """Projeta a foto nas faces voltadas para o eixo, via Blender headless."""

    def __init__(
        self,
        blender_executable: Path | None = None,
        script_path: Path | None = None,
        timeout_seconds: float = 120.0,
    ):
        self.blender_executable = (
            Path(blender_executable)
            if blender_executable is not None
            else _DEFAULT_BLENDER_EXECUTABLE
        )
        self.script_path = Path(script_path) if script_path else _DEFAULT_SCRIPT_PATH
        self.timeout_seconds = timeout_seconds

    async def project(
        self, input: ViewTextureProjectionInput
    ) -> ViewTextureProjectionResult:
        if input.axis not in VALID_AXES:
            raise ViewTextureProjectionError(
                f"Eixo inválido: {input.axis!r} (esperado um de {sorted(VALID_AXES)})"
            )
        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input",  str(input.input_glb),
            "--photo",  str(input.photo),
            "--output", str(input.output_glb),
            "--axis",   input.axis,
            "--cosine-threshold", str(input.cosine_threshold),
        ]

        returncode, _stdout, stderr = await self._run_blender(args)
        rotulo = _ROTULOS.get(input.axis, input.axis)

        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise ViewTextureProjectionError(
                f"Blender retornou {returncode} ao projetar textura de {rotulo}: {tail}"
            )
        if not input.output_glb.exists():
            raise ViewTextureProjectionError(
                "Blender concluiu sem erros mas GLB de saida nao foi criado: "
                f"{input.output_glb}"
            )

        _log.info("Textura de %s projetada: %s", rotulo, input.output_glb)
        return ViewTextureProjectionResult(output_glb=input.output_glb)

    def _assert_runtime_assets(self, input: ViewTextureProjectionInput) -> None:
        if not self.blender_executable.exists():
            raise ViewTextureProjectionError(
                f"Executavel do Blender nao encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise ViewTextureProjectionError(
                f"Script do Blender nao encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise ViewTextureProjectionError(
                f"GLB de entrada nao encontrado: {input.input_glb}"
            )
        if not input.photo.exists():
            raise ViewTextureProjectionError(
                f"Imagem nao encontrada: {input.photo}"
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
            raise ViewTextureProjectionError(
                f"Blender excedeu timeout de {self.timeout_seconds}s ao projetar"
            ) from None
        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )
