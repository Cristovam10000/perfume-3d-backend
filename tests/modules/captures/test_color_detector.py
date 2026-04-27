from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from app.modules.captures.color_detector import (
    AverageColorDetector,
    ColorDetector,
    DisabledColorDetector,
)


def _make_solid_png(path: Path, color: tuple[int, int, int], size: int = 16) -> None:
    """Gera PNG sólido da cor dada usando apenas stdlib."""
    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, level=9)
    path.write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# ---------------------------------------------------------- DisabledColorDetector


class TestDisabledColorDetector:
    def test_is_color_detector_subclass(self):
        assert issubclass(DisabledColorDetector, ColorDetector)

    @pytest.mark.asyncio
    async def test_returns_none_for_any_input(self, tmp_path: Path):
        detector = DisabledColorDetector()
        result = await detector.detect([tmp_path / "x.jpg"])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_list(self):
        detector = DisabledColorDetector()
        assert await detector.detect([]) is None


# ---------------------------------------------------------- AverageColorDetector


class TestAverageColorDetector:
    def test_invalid_crop_ratio_raises(self):
        with pytest.raises(ValueError):
            AverageColorDetector(crop_ratio=0.0)
        with pytest.raises(ValueError):
            AverageColorDetector(crop_ratio=-0.1)
        with pytest.raises(ValueError):
            AverageColorDetector(crop_ratio=1.5)

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_list(self):
        detector = AverageColorDetector()
        assert await detector.detect([]) is None

    @pytest.mark.asyncio
    async def test_red_image_returns_red_hex(self, tmp_path: Path):
        img = tmp_path / "red.png"
        _make_solid_png(img, color=(255, 0, 0))
        detector = AverageColorDetector()

        result = await detector.detect([img])
        assert result == "#FF0000"

    @pytest.mark.asyncio
    async def test_green_image_returns_green_hex(self, tmp_path: Path):
        img = tmp_path / "green.png"
        _make_solid_png(img, color=(0, 255, 0))
        detector = AverageColorDetector()

        result = await detector.detect([img])
        assert result == "#00FF00"

    @pytest.mark.asyncio
    async def test_average_across_multiple_images(self, tmp_path: Path):
        # Duas imagens: uma 100% vermelha, uma 100% azul.
        # Média esperada: rgb(127, 0, 127) ≈ #7F007F
        red = tmp_path / "red.png"
        blue = tmp_path / "blue.png"
        _make_solid_png(red, color=(255, 0, 0))
        _make_solid_png(blue, color=(0, 0, 255))

        detector = AverageColorDetector()
        result = await detector.detect([red, blue])

        # Pode ter arredondamento (127 ou 128)
        assert result in ("#7F007F", "#800080")

    @pytest.mark.asyncio
    async def test_invalid_image_is_skipped_not_fatal(self, tmp_path: Path):
        good = tmp_path / "good.png"
        bad = tmp_path / "bad.png"
        _make_solid_png(good, color=(100, 200, 50))
        bad.write_bytes(b"this is not a png")

        detector = AverageColorDetector()
        result = await detector.detect([good, bad])
        # Resultado deve refletir só a imagem válida
        assert result == "#64C832"  # (100, 200, 50) em hex

    @pytest.mark.asyncio
    async def test_only_invalid_images_returns_none(self, tmp_path: Path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"garbage")

        detector = AverageColorDetector()
        assert await detector.detect([bad]) is None

    @pytest.mark.asyncio
    async def test_hex_format_is_uppercase_with_hash_prefix(self, tmp_path: Path):
        img = tmp_path / "any.png"
        _make_solid_png(img, color=(170, 187, 204))
        detector = AverageColorDetector()

        result = await detector.detect([img])
        assert result is not None
        assert result.startswith("#")
        assert len(result) == 7
        assert result == result.upper()

    @pytest.mark.asyncio
    async def test_prefers_colored_bottle_pixels_over_white_background(
        self,
        tmp_path: Path,
    ):
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (120, 180), color=(240, 240, 235))
        draw = ImageDraw.Draw(img)
        draw.rectangle((45, 55, 75, 145), fill=(32, 72, 130))
        path = tmp_path / "blue_bottle.png"
        img.save(path)

        detector = AverageColorDetector(crop_ratio=0.8)

        assert await detector.detect([path]) == "#204882"
