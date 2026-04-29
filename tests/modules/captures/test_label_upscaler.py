"""Testes do LabelUpscaler."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.captures.label_upscaler import (
    DisabledLabelUpscaler,
    LabelUpscaler,
    LanczosLabelUpscaler,
)


def _make_image(path: Path, *, size: tuple[int, int], mode: str = "RGB") -> None:
    Image = pytest.importorskip("PIL.Image")
    from PIL import Image as PILImage

    if mode == "RGBA":
        cor = (80, 120, 200, 96)
    else:
        cor = (80, 120, 200)
    img = PILImage.new(mode, size, cor)
    img.save(path)


class TestDisabledLabelUpscaler:
    def test_is_label_upscaler_subclass(self):
        assert issubclass(DisabledLabelUpscaler, LabelUpscaler)

    @pytest.mark.asyncio
    async def test_copies_byte_for_byte(self, tmp_path: Path):
        entrada = tmp_path / "label.png"
        saida = tmp_path / "out.png"
        _make_image(entrada, size=(64, 32))
        original = entrada.read_bytes()

        upscaler = DisabledLabelUpscaler()
        await upscaler.upscale(entrada, saida)

        assert saida.read_bytes() == original


class TestLanczosLabelUpscaler:
    def test_is_label_upscaler_subclass(self):
        assert issubclass(LanczosLabelUpscaler, LabelUpscaler)

    def test_invalid_target_size_raises(self):
        with pytest.raises(ValueError):
            LanczosLabelUpscaler(target_size=0)

    @pytest.mark.asyncio
    async def test_upscales_to_target_size(self, tmp_path: Path):
        Image = pytest.importorskip("PIL.Image")
        from PIL import Image as PILImage

        entrada = tmp_path / "label.png"
        saida = tmp_path / "up.png"
        _make_image(entrada, size=(200, 100))

        await LanczosLabelUpscaler(target_size=2048).upscale(entrada, saida)

        with PILImage.open(saida) as img:
            assert img.size == (2048, 1024)

    @pytest.mark.asyncio
    async def test_preserves_alpha_channel(self, tmp_path: Path):
        Image = pytest.importorskip("PIL.Image")
        from PIL import Image as PILImage

        entrada = tmp_path / "label_rgba.png"
        saida = tmp_path / "up.png"
        _make_image(entrada, size=(100, 50), mode="RGBA")

        await LanczosLabelUpscaler(target_size=256).upscale(entrada, saida)

        with PILImage.open(saida) as img:
            assert img.mode == "RGBA"
            assert "A" in img.getbands()

    @pytest.mark.asyncio
    async def test_aspect_ratio_preserved(self, tmp_path: Path):
        Image = pytest.importorskip("PIL.Image")
        from PIL import Image as PILImage

        entrada = tmp_path / "wide.png"
        saida = tmp_path / "up.png"
        _make_image(entrada, size=(300, 100))

        await LanczosLabelUpscaler(target_size=900).upscale(entrada, saida)

        with PILImage.open(saida) as img:
            largura, altura = img.size
            assert largura == 900
            assert abs((largura / altura) - 3.0) < 0.02

    @pytest.mark.asyncio
    async def test_smaller_input_is_still_upscaled(self, tmp_path: Path):
        Image = pytest.importorskip("PIL.Image")
        from PIL import Image as PILImage

        entrada = tmp_path / "small.png"
        saida = tmp_path / "up.png"
        _make_image(entrada, size=(32, 16))

        await LanczosLabelUpscaler(target_size=128).upscale(entrada, saida)

        with PILImage.open(saida) as img:
            assert img.size == (128, 64)
