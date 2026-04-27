"""Testes do TemplateProcessor.

Estratégia:
- Maioria dos testes mocka o método `_run_blender` (rápido, deterministico)
- Um teste de integração real chama Blender de verdade (~5s, pulado se ausente)
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.processor import (
    ProcessingError,
    ProcessingInput,
    TemplateProcessor,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "customize_template.py"
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


def _make_processor(tmp_path: Path) -> TemplateProcessor:
    """Cria TemplateProcessor com paths fingidos que existem em disco."""
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("placeholder")
    fake_script = tmp_path / "customize_template.py"
    fake_script.write_text("# placeholder")
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "rectangular_basic.glb").write_bytes(_minimal_glb())

    return TemplateProcessor(
        blender_executable=fake_blender,
        script_path=fake_script,
        templates_dir=templates_dir,
    )


def _make_input(tmp_path: Path, **overrides) -> ProcessingInput:
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\x00fake")
    defaults = dict(
        job_id="job-test",
        image_paths=[photo],
        output_path=tmp_path / "out" / "model.glb",
    )
    defaults.update(overrides)
    return ProcessingInput(**defaults)


# ----------------------------------------------------------- testes mockados


class TestTemplateProcessorMocked:
    @pytest.mark.asyncio
    async def test_success_returns_result_with_output_path(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, captured = _make_fake_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            result = await proc.process(_make_input(tmp_path))

        assert result.output_path == tmp_path / "out" / "model.glb"
        assert result.output_path.exists()
        assert "rectangular_basic" in result.message
        assert len(captured["calls"]) == 1

    @pytest.mark.asyncio
    async def test_args_include_template_and_output(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, captured = _make_fake_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(_make_input(tmp_path))

        args = captured["calls"][0]
        assert "--template" in args
        assert "--output" in args
        assert "--background" in args
        assert "--python" in args

    @pytest.mark.asyncio
    async def test_label_image_arg_not_passed_by_default(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, captured = _make_fake_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(_make_input(tmp_path))

        args = captured["calls"][0]
        assert "--label-image" not in args

    @pytest.mark.asyncio
    async def test_explicit_label_image_is_passed(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, captured = _make_fake_runner()

        custom_label = tmp_path / "custom_label.png"
        custom_label.write_bytes(b"\x89PNGfake")
        inp = _make_input(tmp_path, label_image=custom_label)

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(inp)

        args = captured["calls"][0]
        idx = args.index("--label-image")
        assert args[idx + 1] == str(custom_label)

    @pytest.mark.asyncio
    async def test_liquid_color_arg_passed_when_provided(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path, liquid_color="#FFAA00")

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(inp)

        args = captured["calls"][0]
        assert "--liquid-color" in args
        assert args[args.index("--liquid-color") + 1] == "#FFAA00"

    @pytest.mark.asyncio
    async def test_uses_input_template_id_when_provided(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        # cria template alternativo no diretório
        alt_template = proc.templates_dir / "cylindrical.glb"
        alt_template.write_bytes(_minimal_glb())
        run, captured = _make_fake_runner()
        inp = _make_input(tmp_path, template_id="cylindrical")

        with patch.object(proc, "_run_blender", side_effect=run):
            result = await proc.process(inp)

        assert "cylindrical" in result.message
        args = captured["calls"][0]
        idx = args.index("--template")
        assert args[idx + 1].endswith("cylindrical.glb")

    @pytest.mark.asyncio
    async def test_blender_nonzero_returncode_raises(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, _ = _make_fake_runner(returncode=1, stderr=b"erro fatal", create_output=False)

        with patch.object(proc, "_run_blender", side_effect=run):
            with pytest.raises(ProcessingError, match="retornou 1"):
                await proc.process(_make_input(tmp_path))

    @pytest.mark.asyncio
    async def test_output_not_created_raises(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        # subprocess "sucesso" mas não cria o output
        run, _ = _make_fake_runner(returncode=0, create_output=False)

        with patch.object(proc, "_run_blender", side_effect=run):
            with pytest.raises(ProcessingError, match="GLB de saída não foi criado"):
                await proc.process(_make_input(tmp_path))

    @pytest.mark.asyncio
    async def test_missing_blender_executable_raises_pre_run(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        proc.blender_executable.unlink()  # remove o "blender" fake

        with pytest.raises(ProcessingError, match="Blender não encontrado"):
            await proc.process(_make_input(tmp_path))

    @pytest.mark.asyncio
    async def test_missing_template_id_raises(self, tmp_path: Path):
        proc = _make_processor(tmp_path)
        run, _ = _make_fake_runner()
        inp = _make_input(tmp_path, template_id="does_not_exist")

        with patch.object(proc, "_run_blender", side_effect=run):
            with pytest.raises(ProcessingError, match="does_not_exist"):
                await proc.process(inp)


    @pytest.mark.asyncio
    async def test_run_blender_captures_process_output(self, tmp_path: Path):
        proc = _make_processor(tmp_path)

        returncode, stdout, stderr = await proc._run_blender(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.write('stdout-ok'); "
                    "sys.stderr.write('stderr-ok'); "
                    "raise SystemExit(7)"
                ),
            ]
        )

        assert returncode == 7
        assert stdout == b"stdout-ok"
        assert stderr == b"stderr-ok"


# ----------------------------------------------------------- teste integração

class TestTemplateProcessorIntegration:
    @pytest.mark.asyncio
    async def test_real_blender_produces_valid_glb(self, tmp_path: Path):
        blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
        if not blender.exists():
            pytest.skip(f"Blender não encontrado em {blender}")
        if not NORMALIZED_TEMPLATE.exists():
            pytest.skip(f"Template normalizado ausente: {NORMALIZED_TEMPLATE}")

        proc = TemplateProcessor(
            blender_executable=blender,
            script_path=SCRIPT_PATH,
            templates_dir=NORMALIZED_TEMPLATE.parent,
            timeout_seconds=60.0,
        )

        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\x00fake")
        output = tmp_path / "out" / "real.glb"

        result = await proc.process(
            ProcessingInput(
                job_id="real-test",
                image_paths=[photo],
                output_path=output,
                liquid_color="#FFAA00",
            )
        )

        assert result.output_path == output
        assert output.exists()
        # Magic header
        assert output.read_bytes()[:4] == b"glTF"
