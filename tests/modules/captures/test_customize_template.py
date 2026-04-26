"""Testes de integração do script customize_template.py.

Os testes invocam Blender de verdade via subprocess. Se o executável não
estiver disponível (CI sem Blender), os testes são pulados — não falham.
"""

from __future__ import annotations

import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "customize_template.py"
TEMPLATE_PATH = BACK_ROOT / "assets" / "templates" / "normalized" / "rectangular_basic.glb"

DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
BLENDER_EXE = Path(os.environ.get("BLENDER_EXECUTABLE", DEFAULT_BLENDER))


def _blender_or_skip() -> Path:
    if not BLENDER_EXE.exists():
        pytest.skip(
            f"Blender não encontrado em {BLENDER_EXE}. "
            "Defina BLENDER_EXECUTABLE para rodar estes testes."
        )
    if not TEMPLATE_PATH.exists():
        pytest.skip(
            f"Template normalizado ausente: {TEMPLATE_PATH}. "
            "Rode scripts/blender/normalize_rectangular_basic.py antes."
        )
    return BLENDER_EXE


def _create_test_png(path: Path, color: tuple[int, int, int] = (200, 50, 50)) -> None:
    """Gera um PNG 8x8 da cor sólida usando apenas stdlib."""
    width = height = 8
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, level=9)
    path.write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def _run_blender(args: list[str], blender: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [
        str(blender),
        "--background",
        "--python", str(SCRIPT_PATH),
        "--",
        *args,
    ]
    # encoding="utf-8" + errors="replace" garante que strings com acento do
    # script Blender venham legíveis no stdout capturado (Windows usa cp1252
    # por padrão).
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _validate_glb(path: Path) -> None:
    data = path.read_bytes()
    assert len(data) >= 20, f"GLB muito curto: {path}"
    magic, version, _ = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67
    assert version == 2


class TestCustomizeTemplate:
    def test_minimal_run_produces_valid_glb(self, tmp_path: Path):
        blender = _blender_or_skip()
        output = tmp_path / "out.glb"

        result = _run_blender(
            [
                "--template", str(TEMPLATE_PATH),
                "--output", str(output),
            ],
            blender=blender,
        )

        assert result.returncode == 0, (
            f"Blender retornou {result.returncode}\n"
            f"stdout: {result.stdout[-1000:]}\n"
            f"stderr: {result.stderr[-1000:]}"
        )
        assert output.exists()
        _validate_glb(output)

    def test_with_liquid_color(self, tmp_path: Path):
        blender = _blender_or_skip()
        output = tmp_path / "out.glb"

        result = _run_blender(
            [
                "--template", str(TEMPLATE_PATH),
                "--output", str(output),
                "--liquid-color", "#FFAA00",
            ],
            blender=blender,
        )

        assert result.returncode == 0, result.stderr[-500:]
        assert output.exists()
        _validate_glb(output)
        # Asserto sem acento pra evitar flakiness por encoding em Windows.
        assert "rgba=" in result.stdout

    def test_with_label_image(self, tmp_path: Path):
        blender = _blender_or_skip()
        label = tmp_path / "label.png"
        _create_test_png(label, color=(220, 60, 60))
        output = tmp_path / "out.glb"

        result = _run_blender(
            [
                "--template", str(TEMPLATE_PATH),
                "--output", str(output),
                "--label-image", str(label),
            ],
            blender=blender,
        )

        assert result.returncode == 0, result.stderr[-500:]
        assert output.exists()
        _validate_glb(output)
        # Asserto sem acento pra evitar flakiness por encoding em Windows.
        assert "label.png" in result.stdout

    def test_with_label_and_color(self, tmp_path: Path):
        blender = _blender_or_skip()
        label = tmp_path / "label.png"
        _create_test_png(label)
        output = tmp_path / "out.glb"

        result = _run_blender(
            [
                "--template", str(TEMPLATE_PATH),
                "--output", str(output),
                "--label-image", str(label),
                "--liquid-color", "#3344FF",
            ],
            blender=blender,
        )

        assert result.returncode == 0, result.stderr[-500:]
        _validate_glb(output)

    def test_invalid_template_fails_with_nonzero_exit(self, tmp_path: Path):
        blender = _blender_or_skip()
        missing = tmp_path / "does-not-exist.glb"
        result = _run_blender(
            [
                "--template", str(missing),
                "--output", str(tmp_path / "out.glb"),
            ],
            blender=blender,
        )
        assert result.returncode != 0
        # Sai com erro e o output não existe — invariantes principais.
        assert not (tmp_path / "out.glb").exists()
        assert "FileNotFoundError" in result.stderr or "FileNotFoundError" in result.stdout

    def test_invalid_color_fails(self, tmp_path: Path):
        blender = _blender_or_skip()
        result = _run_blender(
            [
                "--template", str(TEMPLATE_PATH),
                "--output", str(tmp_path / "out.glb"),
                "--liquid-color", "not-a-hex",
            ],
            blender=blender,
        )
        assert result.returncode != 0
