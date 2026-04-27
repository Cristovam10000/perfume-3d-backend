from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.captures.background_remover import (
    BackgroundRemover,
    DisabledBackgroundRemover,
    RembgBackgroundRemover,
)


# ---------------------------------------------------------- helpers de fixtures


def _make_solid_png(path: Path, color: tuple[int, int, int], size: int = 16) -> None:
    """Gera PNG RGB sólido usando apenas stdlib."""
    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, level=9)
    path.write_bytes(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def _make_rgba_png(path: Path, size: int = 16) -> None:
    """Gera PNG RGBA com fundo transparente e frasco opaco no centro — stdlib."""
    linhas = []
    for y in range(size):
        linha = b"\x00"  # filtro de linha
        for x in range(size):
            dentro = size // 4 <= x < 3 * size // 4 and size // 4 <= y < 3 * size // 4
            a = 255 if dentro else 0
            linha += bytes([180, 120, 60, a])
        linhas.append(linha)
    raw = b"".join(linhas)

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # colortype=6 = RGBA
    idat = zlib.compress(raw, level=9)
    path.write_bytes(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------- DisabledBackgroundRemover


class TestDisabledBackgroundRemover:
    def test_is_background_remover_subclass(self):
        assert issubclass(DisabledBackgroundRemover, BackgroundRemover)

    @pytest.mark.asyncio
    async def test_copia_arquivo_para_output(self, tmp_path: Path):
        entrada = tmp_path / "frasco.png"
        saida = tmp_path / "mascara.png"
        _make_solid_png(entrada, color=(255, 128, 0))

        remover = DisabledBackgroundRemover()
        resultado = await remover.remove(entrada, saida)

        assert resultado == saida
        assert saida.exists()
        assert saida.read_bytes() == entrada.read_bytes()

    @pytest.mark.asyncio
    async def test_cria_diretorio_pai_se_ausente(self, tmp_path: Path):
        entrada = tmp_path / "frasco.png"
        saida = tmp_path / "subdir" / "mascara.png"
        _make_solid_png(entrada, color=(0, 0, 255))

        remover = DisabledBackgroundRemover()
        await remover.remove(entrada, saida)

        assert saida.exists()

    @pytest.mark.asyncio
    async def test_arquivo_inexistente_levanta_file_not_found(self, tmp_path: Path):
        remover = DisabledBackgroundRemover()
        with pytest.raises(FileNotFoundError):
            await remover.remove(tmp_path / "nao_existe.png", tmp_path / "out.png")


# ---------------------------------------------------------- RembgBackgroundRemover


class TestRembgBackgroundRemover:
    def test_is_background_remover_subclass(self):
        assert issubclass(RembgBackgroundRemover, BackgroundRemover)

    def test_model_name_padrao(self):
        remover = RembgBackgroundRemover()
        assert remover.model_name == "isnet-general-use"

    def test_model_name_customizado(self):
        remover = RembgBackgroundRemover(model_name="u2net")
        assert remover.model_name == "u2net"

    @pytest.mark.asyncio
    async def test_arquivo_inexistente_levanta_file_not_found(self, tmp_path: Path):
        rembg = pytest.importorskip("rembg")  # noqa: F841
        remover = RembgBackgroundRemover()
        with pytest.raises(FileNotFoundError):
            await remover.remove(tmp_path / "nao_existe.png", tmp_path / "out.png")

    @pytest.mark.asyncio
    async def test_output_e_png_rgba(self, tmp_path: Path):
        rembg = pytest.importorskip("rembg")  # noqa: F841
        from PIL import Image

        entrada = tmp_path / "frasco.png"
        saida = tmp_path / "mascara.png"
        _make_solid_png(entrada, color=(200, 100, 50), size=64)

        remover = RembgBackgroundRemover()
        resultado = await remover.remove(entrada, saida)

        assert resultado == saida
        assert saida.exists()
        with Image.open(saida) as img:
            assert img.format == "PNG"
            assert img.mode == "RGBA"

    @pytest.mark.asyncio
    async def test_sessao_reutilizada_entre_chamadas(self, tmp_path: Path):
        """new_session deve ser chamado apenas uma vez, mesmo com múltiplas chamadas."""
        pytest.importorskip("rembg")

        from PIL import Image

        # Imagem RGBA falsa para simular o retorno do rembg.remove.
        imagem_falsa = Image.new("RGBA", (16, 16), (0, 0, 0, 0))

        sessao_mock = MagicMock()

        with patch("rembg.new_session", return_value=sessao_mock) as mock_new_session, \
             patch("rembg.remove", return_value=imagem_falsa):

            remover = RembgBackgroundRemover()

            for i in range(3):
                entrada = tmp_path / f"frasco_{i}.png"
                saida = tmp_path / f"mascara_{i}.png"
                _make_solid_png(entrada, color=(100, 100, 100))
                await remover.remove(entrada, saida)

            assert mock_new_session.call_count == 1
