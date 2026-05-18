from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from eval.synthetic_dataset import (
    CARDINAL_VIEWS,
    SyntheticRenderError,
    SyntheticRenderResult,
    render_synthetic_views,
)


# ----------------------------------------------------------------- helpers


def _create_fake_glb(path: Path) -> None:
    """Cria um GLB válido mínimo para passar pelo check `glb_path.exists()`.

    O Blender é mockado nestes testes — o conteúdo do arquivo não importa,
    só o fato de existir.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF\x02\x00\x00\x00")  # magic header


def _create_fake_script(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stub", encoding="utf-8")


def _create_fake_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#!/bin/false\n")


# ---------------------------------------------------------- input validation


class TestInputValidation:
    def test_raises_when_glb_missing(self, tmp_path: Path):
        script = tmp_path / "script.py"
        exe = tmp_path / "blender.exe"
        _create_fake_script(script)
        _create_fake_executable(exe)

        with pytest.raises(FileNotFoundError, match="GLB"):
            render_synthetic_views(
                glb_path=tmp_path / "missing.glb",
                output_dir=tmp_path / "out",
                blender_executable=exe,
                script_path=script,
            )

    def test_raises_when_script_missing(self, tmp_path: Path):
        glb = tmp_path / "in.glb"
        exe = tmp_path / "blender.exe"
        _create_fake_glb(glb)
        _create_fake_executable(exe)

        with pytest.raises(FileNotFoundError, match="Script"):
            render_synthetic_views(
                glb_path=glb,
                output_dir=tmp_path / "out",
                blender_executable=exe,
                script_path=tmp_path / "missing.py",
            )

    def test_raises_when_blender_missing(self, tmp_path: Path):
        glb = tmp_path / "in.glb"
        script = tmp_path / "script.py"
        _create_fake_glb(glb)
        _create_fake_script(script)

        with pytest.raises(FileNotFoundError, match="Blender"):
            render_synthetic_views(
                glb_path=glb,
                output_dir=tmp_path / "out",
                blender_executable=tmp_path / "missing.exe",
                script_path=script,
            )


# -------------------------------------------------------------- success path


class TestSuccessPath:
    @pytest.fixture
    def setup_files(self, tmp_path: Path):
        glb = tmp_path / "in.glb"
        script = tmp_path / "script.py"
        exe = tmp_path / "blender.exe"
        _create_fake_glb(glb)
        _create_fake_script(script)
        _create_fake_executable(exe)
        return {"glb": glb, "script": script, "exe": exe, "out": tmp_path / "out"}

    def test_returns_result_with_all_views(self, setup_files):
        # Mock o subprocess: simula Blender que escreve os 4 PNGs e sai com 0.
        def fake_run(cmd, **kwargs):
            # Extrai output_dir do cmd
            idx = cmd.index("--output-dir")
            out_dir = Path(cmd[idx + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in CARDINAL_VIEWS:
                (out_dir / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = render_synthetic_views(
                glb_path=setup_files["glb"],
                output_dir=setup_files["out"],
                blender_executable=setup_files["exe"],
                script_path=setup_files["script"],
            )

        assert isinstance(result, SyntheticRenderResult)
        assert set(result.views.keys()) == set(CARDINAL_VIEWS)
        for view, path in result.views.items():
            assert path.exists(), f"{view} não foi criado"

    def test_passes_resolution_to_blender(self, setup_files):
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            out_dir = Path(cmd[cmd.index("--output-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in CARDINAL_VIEWS:
                (out_dir / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            render_synthetic_views(
                glb_path=setup_files["glb"],
                output_dir=setup_files["out"],
                blender_executable=setup_files["exe"],
                script_path=setup_files["script"],
                resolution=2048,
                rotate_z_deg=45.0,
            )

        cmd = captured[0]
        assert "2048" in cmd
        assert "45.0" in cmd


# ---------------------------------------------------------------- failures


class TestFailures:
    @pytest.fixture
    def setup_files(self, tmp_path: Path):
        glb = tmp_path / "in.glb"
        script = tmp_path / "script.py"
        exe = tmp_path / "blender.exe"
        _create_fake_glb(glb)
        _create_fake_script(script)
        _create_fake_executable(exe)
        return {"glb": glb, "script": script, "exe": exe, "out": tmp_path / "out"}

    def test_raises_when_blender_returns_error(self, setup_files):
        with patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="blender boom"
            ),
        ):
            with pytest.raises(SyntheticRenderError, match="código 1"):
                render_synthetic_views(
                    glb_path=setup_files["glb"],
                    output_dir=setup_files["out"],
                    blender_executable=setup_files["exe"],
                    script_path=setup_files["script"],
                )

    def test_raises_when_pngs_not_generated(self, setup_files):
        # Blender retorna 0 mas não escreve os PNGs (bug no script, p.ex.)
        with patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="silent fail", stderr=""
            ),
        ):
            with pytest.raises(SyntheticRenderError, match="não geradas"):
                render_synthetic_views(
                    glb_path=setup_files["glb"],
                    output_dir=setup_files["out"],
                    blender_executable=setup_files["exe"],
                    script_path=setup_files["script"],
                )

    def test_raises_on_timeout(self, setup_files):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="blender", timeout=10),
        ):
            with pytest.raises(SyntheticRenderError, match="excedeu"):
                render_synthetic_views(
                    glb_path=setup_files["glb"],
                    output_dir=setup_files["out"],
                    blender_executable=setup_files["exe"],
                    script_path=setup_files["script"],
                    timeout_seconds=10.0,
                )


# --------------------------------------------------------- module constants


def test_cardinal_views_constant():
    assert CARDINAL_VIEWS == ("front", "left", "back", "right")
