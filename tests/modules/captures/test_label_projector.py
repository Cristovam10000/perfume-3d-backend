"""Testes do LabelProjector."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.label_projector import (
    BlenderLabelProjector,
    DisabledLabelProjector,
    LabelProjectionError,
    LabelProjectionInput,
    LabelProjector,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "project_label.py"
)
NORMALIZED_TEMPLATE = (
    BACK_ROOT / "assets" / "templates" / "normalized" / "rectangular_basic.glb"
)
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")


def _minimal_glb() -> bytes:
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


def _make_label(path: Path, *, size: tuple[int, int] = (1024, 512)) -> None:
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    from PIL import Image as PILImage
    from PIL import ImageDraw as PILImageDraw

    img = PILImage.new("RGBA", size, (245, 236, 215, 255))
    draw = PILImageDraw.Draw(img)
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(20, 20, 20), width=8)
    draw.text((80, size[1] // 2 - 30), "PERFUME TEST", fill=(10, 10, 10))
    img.save(path)


def _make_fake_runner(
    *,
    returncode: int = 0,
    stdout: bytes = b"STATS:target_face_index=42,coverage_ratio=0.42\n",
    stderr: bytes = b"",
    create_output: bool = True,
):
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


def _make_projector(tmp_path: Path) -> BlenderLabelProjector:
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("placeholder")
    fake_script = tmp_path / "project_label.py"
    fake_script.write_text("# placeholder")
    return BlenderLabelProjector(
        blender_executable=fake_blender,
        script_path=fake_script,
        timeout_seconds=120.0,
    )


def _make_input(tmp_path: Path, **overrides) -> LabelProjectionInput:
    glb = tmp_path / "in.glb"
    glb.write_bytes(_minimal_glb())
    label = tmp_path / "label.png"
    _make_label(label)
    defaults = dict(
        input_glb=glb,
        label_image=label,
        output_glb=tmp_path / "with_label.glb",
    )
    defaults.update(overrides)
    return LabelProjectionInput(**defaults)


class TestDisabledLabelProjector:
    def test_is_label_projector_subclass(self):
        assert issubclass(DisabledLabelProjector, LabelProjector)

    @pytest.mark.asyncio
    async def test_copies_input_to_output(self, tmp_path: Path):
        projector = DisabledLabelProjector()
        inp = _make_input(tmp_path)

        resultado = await projector.project(inp)

        assert resultado.output_glb == inp.output_glb
        assert inp.output_glb.read_bytes() == inp.input_glb.read_bytes()
        assert resultado.target_face_index == -1


class TestBlenderLabelProjectorMocked:
    @pytest.mark.asyncio
    async def test_args_include_input_label_output_and_axis(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path, front_axis="front_x_pos")

        with patch.object(projector, "_run_blender", side_effect=run):
            await projector.project(inp)

        args = captured["calls"][0]
        assert "--input" in args
        assert "--label" in args
        assert "--output" in args
        assert "--front-axis" in args
        assert args[args.index("--front-axis") + 1] == "front_x_pos"

    @pytest.mark.asyncio
    async def test_parses_stats_from_stdout(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        run, _ = _make_fake_runner(
            stdout=b"pre\nSTATS:target_face_index=7,coverage_ratio=0.375\n"
        )
        inp = _make_input(tmp_path)

        with patch.object(projector, "_run_blender", side_effect=run):
            resultado = await projector.project(inp)

        assert resultado.target_face_index == 7
        assert resultado.coverage_ratio == pytest.approx(0.375)

    @pytest.mark.asyncio
    async def test_nonzero_returncode_raises(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        run, _ = _make_fake_runner(returncode=1, stderr=b"erro", create_output=False)
        inp = _make_input(tmp_path)

        with patch.object(projector, "_run_blender", side_effect=run):
            with pytest.raises(LabelProjectionError, match="retornou 1"):
                await projector.project(inp)

    @pytest.mark.asyncio
    async def test_missing_input_raises(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        label = tmp_path / "label.png"
        _make_label(label)
        inp = LabelProjectionInput(
            input_glb=tmp_path / "missing.glb",
            label_image=label,
            output_glb=tmp_path / "out.glb",
        )

        with pytest.raises(LabelProjectionError, match="não encontrado"):
            await projector.project(inp)

    @pytest.mark.asyncio
    async def test_missing_label_raises(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        glb = tmp_path / "in.glb"
        glb.write_bytes(_minimal_glb())
        inp = LabelProjectionInput(
            input_glb=glb,
            label_image=tmp_path / "missing.png",
            output_glb=tmp_path / "out.glb",
        )

        with pytest.raises(LabelProjectionError, match="label"):
            await projector.project(inp)

    @pytest.mark.asyncio
    async def test_output_not_created_raises(self, tmp_path: Path):
        projector = _make_projector(tmp_path)
        run, _ = _make_fake_runner(returncode=0, create_output=False)
        inp = _make_input(tmp_path)

        with patch.object(projector, "_run_blender", side_effect=run):
            with pytest.raises(LabelProjectionError, match="GLB com label não foi criado"):
                await projector.project(inp)


class TestBlenderLabelProjectorIntegration:
    @pytest.mark.asyncio
    async def test_projects_label_on_valid_glb(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        label = tmp_path / "label.png"
        _make_label(label)
        saida = tmp_path / "with_label.glb"
        projector = BlenderLabelProjector(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            timeout_seconds=120.0,
        )

        resultado = await projector.project(
            LabelProjectionInput(
                input_glb=NORMALIZED_TEMPLATE,
                label_image=label,
                output_glb=saida,
            )
        )

        assert resultado.output_glb == saida
        assert resultado.target_face_index >= 0
        assert resultado.coverage_ratio > 0
        assert saida.read_bytes()[:4] == b"glTF"

        gltf = _parse_glb_json(saida)
        nomes = {mat.get("name") for mat in gltf.get("materials", [])}
        assert "LabelMaterial" in nomes


def _parse_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    json_chunk_length, _ = struct.unpack_from("<II", data, 12)
    json_bytes = data[20: 20 + json_chunk_length].decode("utf-8").rstrip()
    return json.loads(json_bytes)
