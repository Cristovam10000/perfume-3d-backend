"""Testes do MeshCleaner.

Estratégia:
- DisabledMeshCleaner: testes diretos sem Blender.
- BlenderMeshCleanerMocked: mocka _run_blender — rápido, determinístico.
- BlenderMeshCleanerIntegration: Blender real (~5-10s, pulado se ausente).
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.mesh_cleaner import (
    BlenderMeshCleaner,
    DisabledMeshCleaner,
    MeshCleanupError,
    MeshCleanupInput,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "cleanup_mesh.py"
)
NORMALIZED_TEMPLATE = (
    BACK_ROOT / "assets" / "templates" / "normalized" / "rectangular_basic.glb"
)
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")


# ----------------------------------------------------------- helpers/fixtures

def _minimal_glb() -> bytes:
    """GLB sintético mínimo — válido o bastante pra magic header check."""
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


def _make_fake_runner(
    *,
    returncode: int = 0,
    stdout: bytes = b"STATS:islands=2,holes=1,faces=1234\n",
    stderr: bytes = b"",
    create_output: bool = True,
):
    """Factory de mock pra `_run_blender`. Captura args, simula stdout/stderr/return."""
    captured: dict[str, list] = {"calls": []}

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        captured["calls"].append(args)
        if create_output and "--output" in args:
            idx = args.index("--output")
            output_path = Path(args[idx + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(_minimal_glb())
        return returncode, stdout, stderr

    return fake_run, captured


def _make_cleaner(tmp_path: Path, *, timeout: float = 120.0) -> BlenderMeshCleaner:
    """Cria BlenderMeshCleaner com executável e script fingidos."""
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("placeholder")
    fake_script = tmp_path / "cleanup_mesh.py"
    fake_script.write_text("# placeholder")
    return BlenderMeshCleaner(
        blender_executable=fake_blender,
        script_path=fake_script,
        timeout_seconds=timeout,
    )


def _make_input(tmp_path: Path, **overrides) -> MeshCleanupInput:
    glb_entrada = tmp_path / "raw.glb"
    glb_entrada.write_bytes(_minimal_glb())
    defaults = dict(
        input_glb=glb_entrada,
        output_glb=tmp_path / "cleaned.glb",
        min_island_ratio=0.1,
    )
    defaults.update(overrides)
    return MeshCleanupInput(**defaults)


# ----------------------------------------------------------- DisabledMeshCleaner

class TestDisabledMeshCleaner:
    @pytest.mark.asyncio
    async def test_copies_input_to_output(self, tmp_path: Path):
        cleaner = DisabledMeshCleaner()
        inp = _make_input(tmp_path)

        resultado = await cleaner.clean(inp)

        assert resultado.output_glb == inp.output_glb
        assert inp.output_glb.exists()
        assert resultado.islands_removed == 0
        assert resultado.holes_filled == 0

    @pytest.mark.asyncio
    async def test_preserves_byte_for_byte(self, tmp_path: Path):
        cleaner = DisabledMeshCleaner()
        conteudo = b"glTFfake_content_xyz_padded_"
        glb_entrada = tmp_path / "raw.glb"
        glb_entrada.write_bytes(conteudo)
        inp = MeshCleanupInput(
            input_glb=glb_entrada,
            output_glb=tmp_path / "out.glb",
        )

        await cleaner.clean(inp)

        assert inp.output_glb.read_bytes() == conteudo

    @pytest.mark.asyncio
    async def test_missing_input_raises(self, tmp_path: Path):
        cleaner = DisabledMeshCleaner()
        inp = MeshCleanupInput(
            input_glb=tmp_path / "nao_existe.glb",
            output_glb=tmp_path / "out.glb",
        )
        with pytest.raises(MeshCleanupError, match="não encontrado"):
            await cleaner.clean(inp)


# ----------------------------------------------------------- BlenderMeshCleaner mocked

class TestBlenderMeshCleanerMocked:
    @pytest.mark.asyncio
    async def test_args_include_input_output_and_ratio(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path, min_island_ratio=0.1)

        with patch.object(cleaner, "_run_blender", side_effect=run):
            await cleaner.clean(inp)

        args = captured["calls"][0]
        assert "--input" in args
        assert "--output" in args
        assert "--background" in args
        assert "--python" in args
        assert "--min-island-ratio" in args
        assert args[args.index("--min-island-ratio") + 1] == "0.1"

    @pytest.mark.asyncio
    async def test_parses_stats_from_stdout(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        run, _ = _make_fake_runner(
            stdout=b"[cleanup] preamble\nSTATS:islands=5,holes=3,faces=8742\nbye\n"
        )
        inp = _make_input(tmp_path)

        with patch.object(cleaner, "_run_blender", side_effect=run):
            resultado = await cleaner.clean(inp)

        assert resultado.islands_removed == 5
        assert resultado.holes_filled == 3
        assert resultado.final_face_count == 8742

    @pytest.mark.asyncio
    async def test_stats_missing_returns_zeros(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        run, _ = _make_fake_runner(stdout=b"sem stats aqui\n")
        inp = _make_input(tmp_path)

        with patch.object(cleaner, "_run_blender", side_effect=run):
            resultado = await cleaner.clean(inp)

        assert resultado.islands_removed == 0
        assert resultado.holes_filled == 0
        assert resultado.final_face_count == 0

    @pytest.mark.asyncio
    async def test_nonzero_returncode_raises(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        run, _ = _make_fake_runner(
            returncode=1, stderr=b"erro fatal", create_output=False
        )
        inp = _make_input(tmp_path)

        with patch.object(cleaner, "_run_blender", side_effect=run):
            with pytest.raises(MeshCleanupError, match="retornou 1"):
                await cleaner.clean(inp)

    @pytest.mark.asyncio
    async def test_missing_input_glb_raises(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        inp = MeshCleanupInput(
            input_glb=tmp_path / "nao_existe.glb",
            output_glb=tmp_path / "out.glb",
        )
        with pytest.raises(MeshCleanupError, match="não encontrado"):
            await cleaner.clean(inp)

    @pytest.mark.asyncio
    async def test_invalid_ratio_raises(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        inp = _make_input(tmp_path, min_island_ratio=1.5)
        with pytest.raises(MeshCleanupError, match="min_island_ratio"):
            await cleaner.clean(inp)

    @pytest.mark.asyncio
    async def test_output_not_created_raises(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        run, _ = _make_fake_runner(returncode=0, create_output=False)
        inp = _make_input(tmp_path)

        with patch.object(cleaner, "_run_blender", side_effect=run):
            with pytest.raises(MeshCleanupError, match="GLB limpo não foi criado"):
                await cleaner.clean(inp)


# ----------------------------------------------------------- BlenderMeshCleaner integração

    @pytest.mark.asyncio
    async def test_zero_ratio_bypasses_blender_and_copies(self, tmp_path: Path):
        cleaner = _make_cleaner(tmp_path)
        conteudo = b"glTFraw_hunyuan_preserved"
        glb_entrada = tmp_path / "raw.glb"
        glb_entrada.write_bytes(conteudo)
        inp = MeshCleanupInput(
            input_glb=glb_entrada,
            output_glb=tmp_path / "cleaned.glb",
            min_island_ratio=0.0,
        )

        with patch.object(cleaner, "_run_blender") as run_mock:
            resultado = await cleaner.clean(inp)

        run_mock.assert_not_called()
        assert inp.output_glb.read_bytes() == conteudo
        assert resultado.islands_removed == 0
        assert resultado.holes_filled == 0
        assert resultado.final_face_count == 0


class TestBlenderMeshCleanerIntegration:
    @pytest.mark.asyncio
    async def test_cleans_valid_input_glb(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        cleaner = BlenderMeshCleaner(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            timeout_seconds=120.0,
        )
        saida = tmp_path / "cleaned.glb"

        resultado = await cleaner.clean(
            MeshCleanupInput(
                input_glb=NORMALIZED_TEMPLATE,
                output_glb=saida,
                min_island_ratio=0.1,
            )
        )

        assert resultado.output_glb == saida
        assert saida.exists()
        assert saida.read_bytes()[:4] == b"glTF"
        # Stats devem ter sido parseadas (face_count > 0 em qualquer GLB real).
        assert resultado.final_face_count > 0

    @pytest.mark.asyncio
    async def test_preserves_main_meshes(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        cleaner = BlenderMeshCleaner(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            timeout_seconds=120.0,
        )
        saida = tmp_path / "cleaned.glb"

        await cleaner.clean(
            MeshCleanupInput(
                input_glb=NORMALIZED_TEMPLATE,
                output_glb=saida,
                min_island_ratio=0.1,
            )
        )

        # GLB de saída deve ter pelo menos um mesh com geometria.
        gltf = _parse_glb_json(saida)
        assert len(gltf.get("meshes", [])) >= 1


# ----------------------------------------------------------- helpers GLB

def _parse_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    json_chunk_length, _ = struct.unpack_from("<II", data, 12)
    json_bytes = data[20: 20 + json_chunk_length].decode("utf-8").rstrip()
    return json.loads(json_bytes)
