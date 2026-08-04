"""Projetor de textura do topo: aplica a foto do topo do frasco na tampa do GLB."""

from __future__ import annotations

import asyncio
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.top_projector")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "project_top_texture.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)


@dataclass(frozen=True)
class TopProjectionInput:
    input_glb: Path
    top_image: Path
    output_glb: Path
    cosine_threshold: float = 0.50


@dataclass(frozen=True)
class TopProjectionResult:
    output_glb: Path


class TopProjectionError(Exception):
    """Falha durante projeção da textura do topo."""


class TopProjector(ABC):
    @abstractmethod
    async def project(self, input: TopProjectionInput) -> TopProjectionResult: ...


class DisabledTopProjector(TopProjector):
    """Bypass: copia o GLB de entrada sem modificar."""

    async def project(self, input: TopProjectionInput) -> TopProjectionResult:
        import shutil
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return TopProjectionResult(output_glb=input.output_glb)


class BlenderTopProjector(TopProjector):
    """Projeta a foto do topo nas faces superiores da tampa via Blender headless."""

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

    async def project(self, input: TopProjectionInput) -> TopProjectionResult:
        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input",  str(input.input_glb),
            "--top",    str(input.top_image),
            "--output", str(input.output_glb),
            "--cosine-threshold", str(input.cosine_threshold),
        ]

        returncode, stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise TopProjectionError(
                f"Blender retornou {returncode} ao projetar textura do topo: {tail}"
            )
        if not input.output_glb.exists():
            raise TopProjectionError(
                f"Blender concluiu sem erros mas GLB de saida nao foi criado: "
                f"{input.output_glb}"
            )

        _log.info("Textura do topo projetada: %s", input.output_glb)
        return TopProjectionResult(output_glb=input.output_glb)

    def _assert_runtime_assets(self, input: TopProjectionInput) -> None:
        if not self.blender_executable.exists():
            raise TopProjectionError(
                f"Executavel do Blender nao encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise TopProjectionError(
                f"Script do Blender nao encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise TopProjectionError(
                f"GLB de entrada nao encontrado: {input.input_glb}"
            )
        if not input.top_image.exists():
            raise TopProjectionError(
                f"Imagem do topo nao encontrada: {input.top_image}"
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
            raise TopProjectionError(
                f"Blender excedeu timeout de {self.timeout_seconds}s ao projetar topo"
            ) from None
        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )
