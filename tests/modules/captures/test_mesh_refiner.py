"""Testes do MeshRefiner.

Estratégia:
- DisabledMeshRefiner: testes diretos sem Blender.
- BlenderMeshRefinerMocked: mocka _run_blender — rápido, determinístico.
- BlenderMeshRefinerIntegration: Blender real (~5-10s, pulado se ausente).
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.mesh_refiner import (
    BlenderMeshRefiner,
    DisabledMeshRefiner,
    MeshRefinementError,
    RefinementInput,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "refine_ai_mesh.py"
)
NORMALIZED_TEMPLATE = BACK_ROOT / "assets" / "templates" / "normalized" / "rectangular_basic.glb"
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")


# ----------------------------------------------------------- helpers/fixtures

def _minimal_glb() -> bytes:
    """GLB sintético mínimo — válido o bastante pra magic header check."""
    json_bytes = b'{"asset":{"version":"2.0"}}  '  # padded para múltiplo de 4
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


def _make_fake_runner(
    *,
    returncode: int = 0,
    stderr: bytes = b"",
    create_output: bool = True,
):
    """Factory de mock pra `_run_blender` que captura args e simula resultado."""
    captured: dict[str, list] = {"calls": []}

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        captured["calls"].append(args)
        if create_output and "--output" in args:
            idx = args.index("--output")
            output_path = Path(args[idx + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(_minimal_glb())
        return returncode, b"", stderr

    return fake_run, captured


def _make_refiner(tmp_path: Path, *, timeout: float = 120.0) -> BlenderMeshRefiner:
    """Cria BlenderMeshRefiner com executável e script fingidos que existem em disco."""
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("placeholder")
    fake_script = tmp_path / "refine_ai_mesh.py"
    fake_script.write_text("# placeholder")
    return BlenderMeshRefiner(
        blender_executable=fake_blender,
        script_path=fake_script,
        timeout_seconds=timeout,
    )


def _make_input(tmp_path: Path, **overrides) -> RefinementInput:
    glb_entrada = tmp_path / "raw.glb"
    glb_entrada.write_bytes(_minimal_glb())
    defaults = dict(
        input_glb=glb_entrada,
        output_glb=tmp_path / "refined.glb",
    )
    defaults.update(overrides)
    return RefinementInput(**defaults)


# ----------------------------------------------------------- DisabledMeshRefiner

class TestDisabledMeshRefiner:
    @pytest.mark.asyncio
    async def test_copies_input_to_output(self, tmp_path: Path):
        refiner = DisabledMeshRefiner()
        inp = _make_input(tmp_path)

        resultado = await refiner.refine(inp)

        assert resultado.output_glb == inp.output_glb
        assert inp.output_glb.exists()

    @pytest.mark.asyncio
    async def test_preserves_byte_for_byte(self, tmp_path: Path):
        refiner = DisabledMeshRefiner()
        conteudo = b"glTFfake_content_xyz_padded_"
        glb_entrada = tmp_path / "raw.glb"
        glb_entrada.write_bytes(conteudo)
        inp = RefinementInput(
            input_glb=glb_entrada,
            output_glb=tmp_path / "out.glb",
        )

        await refiner.refine(inp)

        assert inp.output_glb.read_bytes() == conteudo


# ----------------------------------------------------------- BlenderMeshRefiner mocked

class TestBlenderMeshRefinerMocked:
    @pytest.mark.asyncio
    async def test_args_include_input_and_output(self, tmp_path: Path):
        refiner = _make_refiner(tmp_path)
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path)

        with patch.object(refiner, "_run_blender", side_effect=run):
            await refiner.refine(inp)

        args = captured["calls"][0]
        assert "--input" in args
        assert "--output" in args
        assert "--background" in args
        assert "--python" in args

    @pytest.mark.asyncio
    async def test_liquid_color_is_passed_when_provided(self, tmp_path: Path):
        refiner = _make_refiner(tmp_path)
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path, liquid_color="#FFAA00")

        with patch.object(refiner, "_run_blender", side_effect=run):
            await refiner.refine(inp)

        args = captured["calls"][0]
        assert "--liquid-color" in args
        assert args[args.index("--liquid-color") + 1] == "#FFAA00"

    @pytest.mark.asyncio
    async def test_nonzero_returncode_raises(self, tmp_path: Path):
        refiner = _make_refiner(tmp_path)
        run, _ = _make_fake_runner(returncode=1, stderr=b"erro fatal", create_output=False)
        inp = _make_input(tmp_path)

        with patch.object(refiner, "_run_blender", side_effect=run):
            with pytest.raises(MeshRefinementError, match="retornou 1"):
                await refiner.refine(inp)

    @pytest.mark.asyncio
    async def test_missing_input_glb_raises(self, tmp_path: Path):
        refiner = _make_refiner(tmp_path)
        inp = RefinementInput(
            input_glb=tmp_path / "nao_existe.glb",
            output_glb=tmp_path / "out.glb",
        )

        with pytest.raises(MeshRefinementError, match="não encontrado"):
            await refiner.refine(inp)

    @pytest.mark.asyncio
    async def test_output_not_created_raises(self, tmp_path: Path):
        refiner = _make_refiner(tmp_path)
        run, _ = _make_fake_runner(returncode=0, create_output=False)
        inp = _make_input(tmp_path)

        with patch.object(refiner, "_run_blender", side_effect=run):
            with pytest.raises(MeshRefinementError, match="GLB refinado não foi criado"):
                await refiner.refine(inp)


# ----------------------------------------------------------- BlenderMeshRefiner integração

class TestBlenderMeshRefinerIntegration:
    @pytest.mark.asyncio
    async def test_refines_valid_input_glb(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        refiner = BlenderMeshRefiner(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            timeout_seconds=60.0,
        )
        saida = tmp_path / "refined.glb"

        resultado = await refiner.refine(
            RefinementInput(
                input_glb=NORMALIZED_TEMPLATE,
                output_glb=saida,
            )
        )

        assert resultado.output_glb == saida
        assert saida.exists()
        assert saida.read_bytes()[:4] == b"glTF"

    @pytest.mark.asyncio
    async def test_preserves_textured_materials(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        refiner = BlenderMeshRefiner(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            timeout_seconds=60.0,
        )
        saida = tmp_path / "refined.glb"
        await refiner.refine(
            RefinementInput(
                input_glb=NORMALIZED_TEMPLATE,
                output_glb=saida,
            )
        )

        # Materiais com textura no input não devem desaparecer no output
        entrada_gltf = _parse_glb(NORMALIZED_TEMPLATE)
        saida_gltf = _parse_glb(saida)

        n_entrada = _contar_materiais_com_textura(entrada_gltf)
        n_saida = _contar_materiais_com_textura(saida_gltf)

        assert n_saida >= n_entrada, (
            f"Refinamento removeu materiais texturizados: "
            f"antes={n_entrada}, depois={n_saida}"
        )


# ----------------------------------------------------------- helpers GLB

def _parse_glb(path: Path) -> dict:
    """Extrai e parseia o chunk JSON de um arquivo GLB."""
    data = path.read_bytes()
    json_chunk_length, _ = struct.unpack_from("<II", data, 12)
    json_bytes = data[20: 20 + json_chunk_length].decode("utf-8").rstrip()
    return json.loads(json_bytes)


def _contar_materiais_com_textura(gltf: dict) -> int:
    """Conta materiais que referenciam uma baseColorTexture."""
    contador = 0
    for mat in gltf.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness", {})
        if pbr.get("baseColorTexture") is not None:
            contador += 1
    return contador
