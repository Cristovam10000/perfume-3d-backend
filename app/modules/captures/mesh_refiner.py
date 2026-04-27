"""Refinador de malha: pós-processador que melhora materiais de GLBs gerados por IA."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.mesh_refiner")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "refine_ai_mesh.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)


@dataclass(frozen=True)
class RefinementInput:
    input_glb: Path
    output_glb: Path
    liquid_color: str | None = None


@dataclass(frozen=True)
class RefinementResult:
    output_glb: Path
    message: str


class MeshRefinementError(Exception):
    """Falha durante refinamento. Capturada pelo chamador."""


class MeshRefiner(ABC):
    @abstractmethod
    async def refine(self, input: RefinementInput) -> RefinementResult: ...


class DisabledMeshRefiner(MeshRefiner):
    """Bypass: copia o GLB de entrada sem refinamento. Útil para testes."""

    async def refine(self, input: RefinementInput) -> RefinementResult:
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return RefinementResult(
            output_glb=input.output_glb,
            message="Refinamento desativado — GLB copiado sem alterações",
        )


class BlenderMeshRefiner(MeshRefiner):
    """Refina GLBs invocando Blender headless com refine_ai_mesh.py.

    Mesmo padrão de subprocess do TemplateProcessor:
    - subprocess.run em asyncio.to_thread (compatível com Windows)
    - timeout configurável
    - exit code != 0 vira MeshRefinementError com últimos 500 chars do stderr
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

    async def refine(self, input: RefinementInput) -> RefinementResult:
        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input", str(input.input_glb),
            "--output", str(input.output_glb),
        ]
        if input.liquid_color is not None:
            args.extend(["--liquid-color", input.liquid_color])

        returncode, _stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            trecho = stderr.decode("utf-8", errors="replace")[-500:]
            raise MeshRefinementError(
                f"Blender retornou {returncode} ao refinar malha: {trecho}"
            )

        if not input.output_glb.exists():
            raise MeshRefinementError(
                "Blender concluiu sem erros mas o GLB refinado não foi criado: "
                f"{input.output_glb}"
            )

        return RefinementResult(
            output_glb=input.output_glb,
            message="Malha refinada com shader de vidro PBR",
        )

    def _assert_runtime_assets(self, input: RefinementInput) -> None:
        if not self.blender_executable.exists():
            raise MeshRefinementError(
                f"Executável do Blender não encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise MeshRefinementError(
                f"Script do Blender não encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise MeshRefinementError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )

    async def _run_blender(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Roda o subprocess Blender de forma assíncrona.

        Isolado em método pra permitir override em testes (evita custo de
        invocar o Blender real em cada caso). Retorna (returncode, stdout, stderr).
        """
        return await asyncio.to_thread(self._run_blender_sync, args)

    def _run_blender_sync(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Executa o Blender em uma thread.

        No Windows, alguns event loops não implementam subprocess assíncrono
        nativo. `subprocess.run` dentro de `asyncio.to_thread` mantém o servidor
        responsivo e evita `NotImplementedError` em runtime.
        """
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
            raise MeshRefinementError(
                f"Blender excedeu timeout de {self.timeout_seconds}s"
            ) from None

        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )
