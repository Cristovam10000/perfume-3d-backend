"""Projetor de label: aplica a label real extraída da foto no GLB do frasco."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.label_projector")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "project_label.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)
_STATS_REGEX = re.compile(
    r"STATS:target_face_index=(-?\d+),coverage_ratio=([0-9]*\.?[0-9]+)"
)


@dataclass(frozen=True)
class LabelProjectionInput:
    input_glb: Path
    label_image: Path
    output_glb: Path
    front_axis: str = "front_y_neg"


@dataclass(frozen=True)
class LabelProjectionResult:
    output_glb: Path
    target_face_index: int
    coverage_ratio: float


class LabelProjectionError(Exception):
    """Falha durante projeção da label. Capturada pelo chamador."""


class LabelProjector(ABC):
    @abstractmethod
    async def project(self, input: LabelProjectionInput) -> LabelProjectionResult: ...


class DisabledLabelProjector(LabelProjector):
    """Bypass: copia o GLB sem aplicar label."""

    async def project(self, input: LabelProjectionInput) -> LabelProjectionResult:
        if not input.input_glb.exists():
            raise LabelProjectionError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return LabelProjectionResult(
            output_glb=input.output_glb,
            target_face_index=-1,
            coverage_ratio=0.0,
        )


class BlenderLabelProjector(LabelProjector):
    """Aplica label via Blender headless com projeção UV planar.

    Mesmo padrão dos outros subprocessos Blender do módulo:
    - subprocess.run dentro de asyncio.to_thread
    - timeout configurável
    - exit code != 0 vira LabelProjectionError com trecho do stderr
    - stdout emite STATS parseável para depuração visual
    """

    def __init__(
        self,
        blender_executable: Path | None = None,
        script_path: Path | None = None,
        timeout_seconds: float = 120.0,
    ):
        self.blender_executable = (
            Path(blender_executable)
            if blender_executable is not None
            else Path(
                os.environ.get(
                    "BLENDER_EXECUTABLE",
                    str(_DEFAULT_BLENDER_EXECUTABLE),
                )
            )
        )
        self.script_path = Path(script_path) if script_path else _DEFAULT_SCRIPT_PATH
        self.timeout_seconds = timeout_seconds

    async def project(self, input: LabelProjectionInput) -> LabelProjectionResult:
        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input", str(input.input_glb),
            "--label", str(input.label_image),
            "--output", str(input.output_glb),
            "--front-axis", input.front_axis,
        ]

        returncode, stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            trecho = stderr.decode("utf-8", errors="replace")[-500:]
            raise LabelProjectionError(
                f"Blender retornou {returncode} ao projetar label: {trecho}"
            )

        if not input.output_glb.exists():
            raise LabelProjectionError(
                "Blender concluiu sem erros mas o GLB com label não foi criado: "
                f"{input.output_glb}"
            )

        face_index, cobertura = self._parse_stats(
            stdout.decode("utf-8", errors="replace")
        )
        return LabelProjectionResult(
            output_glb=input.output_glb,
            target_face_index=face_index,
            coverage_ratio=cobertura,
        )

    def _assert_runtime_assets(self, input: LabelProjectionInput) -> None:
        if not self.blender_executable.exists():
            raise LabelProjectionError(
                f"Executável do Blender não encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise LabelProjectionError(
                f"Script do Blender não encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise LabelProjectionError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )
        if not input.label_image.exists():
            raise LabelProjectionError(
                f"Imagem da label não encontrada: {input.label_image}"
            )

    def _parse_stats(self, stdout: str) -> tuple[int, float]:
        match = _STATS_REGEX.search(stdout)
        if match is None:
            _log.warning(
                "STATS não encontrado no stdout do project_label — assumindo zeros"
            )
            return -1, 0.0
        return int(match.group(1)), float(match.group(2))

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
            raise LabelProjectionError(
                f"Blender excedeu timeout de {self.timeout_seconds}s"
            ) from None

        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )
