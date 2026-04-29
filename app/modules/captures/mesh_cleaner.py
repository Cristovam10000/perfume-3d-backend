"""Limpeza de mesh: remove ilhas soltas, fecha furos pequenos e suaviza normais.

Etapa intermediária entre o `Hunyuan3DProcessor` e o `BlenderMeshRefiner`.
A IA gera GLBs com pequenos artefatos: bolinhas isoladas, furos no topo da
tampa, normais invertidas. Este passo aplica limpeza conservadora — sem
remesh agressivo, sem perda de detalhe — para que o refinador receba uma
malha "honesta".

Mesmo padrão Strategy do restante do módulo: ABC + bypass + implementação real.

Implementações disponíveis:
- `DisabledMeshCleaner`: copia o GLB de entrada sem alterações.
- `BlenderMeshCleaner`: subprocess Blender headless com `cleanup_mesh.py`.
"""

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

_log = get_logger("captures.mesh_cleaner")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "cleanup_mesh.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)

# Padrão emitido pelo cleanup_mesh.py em stdout: STATS:islands=N,holes=M,faces=K
_STATS_REGEX = re.compile(
    r"STATS:islands=(\d+),holes=(\d+),faces=(\d+)"
)


@dataclass(frozen=True)
class MeshCleanupInput:
    input_glb: Path
    output_glb: Path
    min_island_ratio: float = 0.0  # 0 = preserva ilhas; Hunyuan fragmenta superfícies úteis


@dataclass(frozen=True)
class MeshCleanupResult:
    output_glb: Path
    islands_removed: int
    holes_filled: int
    final_face_count: int


class MeshCleanupError(Exception):
    """Falha durante limpeza. Capturada pelo chamador."""


class MeshCleaner(ABC):
    @abstractmethod
    async def clean(self, input: MeshCleanupInput) -> MeshCleanupResult: ...


class DisabledMeshCleaner(MeshCleaner):
    """Bypass: copia o GLB sem alterar. Útil em testes e ambientes sem Blender."""

    async def clean(self, input: MeshCleanupInput) -> MeshCleanupResult:
        if not input.input_glb.exists():
            raise MeshCleanupError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )
        input.output_glb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input.input_glb, input.output_glb)
        return MeshCleanupResult(
            output_glb=input.output_glb,
            islands_removed=0,
            holes_filled=0,
            final_face_count=0,
        )


class BlenderMeshCleaner(MeshCleaner):
    """Limpa mesh via Blender headless com `cleanup_mesh.py`.

    Mesmo padrão de subprocess do `BlenderMeshRefiner`:
    - subprocess.run em asyncio.to_thread (compatível com Windows)
    - timeout configurável
    - exit code != 0 vira MeshCleanupError com últimos 500 chars do stderr
    - parsing de stats via regex no stdout
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

    async def clean(self, input: MeshCleanupInput) -> MeshCleanupResult:
        self._assert_common_input(input)

        if input.min_island_ratio <= 0.0:
            _log.info(
                "min_island_ratio=0: copiando GLB sem limpeza para preservar Hunyuan"
            )
            input.output_glb.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input.input_glb, input.output_glb)
            return MeshCleanupResult(
                output_glb=input.output_glb,
                islands_removed=0,
                holes_filled=0,
                final_face_count=0,
            )

        self._assert_runtime_assets(input)

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--input", str(input.input_glb),
            "--output", str(input.output_glb),
            "--min-island-ratio", f"{input.min_island_ratio}",
        ]

        returncode, stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            trecho = stderr.decode("utf-8", errors="replace")[-500:]
            raise MeshCleanupError(
                f"Blender retornou {returncode} ao limpar mesh: {trecho}"
            )

        if not input.output_glb.exists():
            raise MeshCleanupError(
                "Blender concluiu sem erros mas o GLB limpo não foi criado: "
                f"{input.output_glb}"
            )

        ilhas, furos, faces = self._parse_stats(stdout.decode("utf-8", errors="replace"))

        return MeshCleanupResult(
            output_glb=input.output_glb,
            islands_removed=ilhas,
            holes_filled=furos,
            final_face_count=faces,
        )

    # ------------------------------------------------------------------ helpers

    def _assert_common_input(self, input: MeshCleanupInput) -> None:
        if not 0.0 <= input.min_island_ratio < 1.0:
            raise MeshCleanupError(
                "min_island_ratio deve estar em [0.0, 1.0): "
                f"{input.min_island_ratio}"
            )
        if not input.input_glb.exists():
            raise MeshCleanupError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )

    def _assert_runtime_assets(self, input: MeshCleanupInput) -> None:
        if not self.blender_executable.exists():
            raise MeshCleanupError(
                f"Executável do Blender não encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise MeshCleanupError(
                f"Script do Blender não encontrado: {self.script_path}"
            )
        if not input.input_glb.exists():
            raise MeshCleanupError(
                f"GLB de entrada não encontrado: {input.input_glb}"
            )

    def _parse_stats(self, stdout: str) -> tuple[int, int, int]:
        """Extrai (islands_removed, holes_filled, final_face_count) do stdout.

        Se a linha STATS estiver ausente (script falhou após exportar?), retorna
        zeros e loga warning — não levanta, porque o GLB já foi criado.
        """
        match = _STATS_REGEX.search(stdout)
        if match is None:
            _log.warning(
                "STATS não encontrado no stdout do cleanup_mesh — assumindo zeros"
            )
            return 0, 0, 0
        return int(match.group(1)), int(match.group(2)), int(match.group(3))

    async def _run_blender(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Roda o subprocess Blender de forma assíncrona.

        Isolado em método pra permitir override em testes sem invocar o
        Blender real. Retorna (returncode, stdout, stderr).
        """
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
            raise MeshCleanupError(
                f"Blender excedeu timeout de {self.timeout_seconds}s"
            ) from None

        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )
