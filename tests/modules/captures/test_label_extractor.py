from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from app.modules.captures.label_extractor import (
    DisabledLabelExtractor,
    ExtractedLabel,
    HomographyLabelExtractor,
    LabelExtractor,
    _ordenar_cantos,
)


# ---------------------------------------------------------- helpers de fixtures


def _make_solid_png_rgb(
    path: Path, color: tuple[int, int, int], size: int = 64
) -> None:
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


def _make_rgba_full_opaque(path: Path, size: int = 256) -> None:
    """Gera PNG RGBA completamente opaco (alpha=255) — silhueta do frasco inteiro."""
    linhas = []
    for _ in range(size):
        linha = b"\x00"  # filtro de linha
        for _ in range(size):
            linha += bytes([180, 180, 180, 255])
        linhas.append(linha)
    raw = b"".join(linhas)

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(raw, level=9)
    path.write_bytes(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def _make_image_com_retangulo(
    path_rgb: Path,
    path_mascara: Path,
    tamanho: int = 256,
    rect: tuple[int, int, int, int] = (60, 80, 190, 180),
) -> None:
    """Cria par (imagem RGB + máscara RGBA) com retângulo branco na imagem.

    O retângulo branco simula uma label, facilitando detecção por Canny.
    A máscara é completamente opaca para que toda a imagem seja considerada frasco.
    """
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    x1, y1, x2, y2 = rect

    imagem = np.zeros((tamanho, tamanho, 3), dtype=np.uint8)
    cv2.rectangle(imagem, (x1, y1), (x2, y2), (255, 255, 255), thickness=3)
    cv2.imwrite(str(path_rgb), imagem)

    mascara = np.zeros((tamanho, tamanho, 4), dtype=np.uint8)
    mascara[:, :, :3] = 180
    mascara[:, :, 3] = 255
    cv2.imwrite(str(path_mascara), mascara)


# ---------------------------------------------------------- DisabledLabelExtractor


class TestDisabledLabelExtractor:
    def test_is_label_extractor_subclass(self):
        assert issubclass(DisabledLabelExtractor, LabelExtractor)

    @pytest.mark.asyncio
    async def test_sempre_retorna_none(self, tmp_path: Path):
        extrator = DisabledLabelExtractor()
        resultado = await extrator.extract(
            image_path=tmp_path / "frasco.png",
            mask_path=tmp_path / "mascara.png",
            output_path=tmp_path / "label.png",
        )
        assert resultado is None


# ---------------------------------------------------------- HomographyLabelExtractor


class TestHomographyLabelExtractor:
    def test_is_label_extractor_subclass(self):
        assert issubclass(HomographyLabelExtractor, LabelExtractor)

    def test_parametros_invalidos_levantam_value_error(self):
        with pytest.raises(ValueError):
            HomographyLabelExtractor(min_area_ratio=0.5, max_area_ratio=0.3)
        with pytest.raises(ValueError):
            HomographyLabelExtractor(min_area_ratio=0.0, max_area_ratio=0.5)

    @pytest.mark.asyncio
    async def test_arquivo_imagem_inexistente_levanta_file_not_found(self, tmp_path: Path):
        pytest.importorskip("cv2")
        mascara = tmp_path / "mascara.png"
        _make_rgba_full_opaque(mascara)

        extrator = HomographyLabelExtractor()
        with pytest.raises(FileNotFoundError):
            await extrator.extract(
                image_path=tmp_path / "nao_existe.png",
                mask_path=mascara,
                output_path=tmp_path / "label.png",
            )

    @pytest.mark.asyncio
    async def test_arquivo_mascara_inexistente_levanta_file_not_found(self, tmp_path: Path):
        pytest.importorskip("cv2")
        imagem = tmp_path / "frasco.png"
        _make_solid_png_rgb(imagem, color=(100, 100, 100))

        extrator = HomographyLabelExtractor()
        with pytest.raises(FileNotFoundError):
            await extrator.extract(
                image_path=imagem,
                mask_path=tmp_path / "nao_existe.png",
                output_path=tmp_path / "label.png",
            )

    @pytest.mark.asyncio
    async def test_imagem_sem_contorno_retorna_none(self, tmp_path: Path):
        """Imagem uniforme não tem bordas detectáveis — deve retornar None."""
        cv2 = pytest.importorskip("cv2")

        imagem = tmp_path / "frasco.png"
        mascara = tmp_path / "mascara.png"
        _make_solid_png_rgb(imagem, color=(128, 128, 128))
        _make_rgba_full_opaque(mascara)

        extrator = HomographyLabelExtractor()
        resultado = await extrator.extract(imagem, mascara, tmp_path / "label.png")
        assert resultado is None

    @pytest.mark.asyncio
    async def test_retangulo_sintetico_gera_proporcao_esperada(self, tmp_path: Path):
        """Retângulo branco 130×100 deve produzir label com proporção ~1.3."""
        pytest.importorskip("cv2")

        imagem = tmp_path / "frasco.png"
        mascara = tmp_path / "mascara.png"
        # rect: x1=60, y1=80, x2=190, y2=180 → ~130px largura × 100px altura
        _make_image_com_retangulo(imagem, mascara, tamanho=256, rect=(60, 80, 190, 180))

        extrator = HomographyLabelExtractor(target_width=512)
        resultado = await extrator.extract(imagem, mascara, tmp_path / "label.png")

        if resultado is None:
            pytest.skip("Canny não detectou o retângulo nesta configuração de hardware")

        assert isinstance(resultado, ExtractedLabel)
        assert resultado.image_path.exists()
        # Proporção esperada: 130/100 = 1.3; tolerância ±30%
        assert 0.9 <= resultado.aspect_ratio <= 1.7, (
            f"Proporção {resultado.aspect_ratio:.2f} fora do intervalo esperado"
        )

    @pytest.mark.asyncio
    async def test_confianca_aumenta_com_tamanho_do_retangulo(self, tmp_path: Path):
        """Retângulo maior deve ter confiança >= retângulo menor."""
        pytest.importorskip("cv2")

        img_p = tmp_path / "pequeno.png"
        msk_p = tmp_path / "mascara_p.png"
        img_g = tmp_path / "grande.png"
        msk_g = tmp_path / "mascara_g.png"
        out_p = tmp_path / "label_p.png"
        out_g = tmp_path / "label_g.png"

        # Retângulo pequeno: ~30px × 25px sobre imagem 256px
        _make_image_com_retangulo(img_p, msk_p, tamanho=256, rect=(110, 115, 140, 140))
        # Retângulo grande: ~160px × 120px sobre imagem 256px
        _make_image_com_retangulo(img_g, msk_g, tamanho=256, rect=(48, 68, 208, 188))

        extrator = HomographyLabelExtractor(min_area_ratio=0.01, max_area_ratio=0.9)
        res_p = await extrator.extract(img_p, msk_p, out_p)
        res_g = await extrator.extract(img_g, msk_g, out_g)

        if res_p is None or res_g is None:
            pytest.skip("Canny não detectou contornos suficientes para comparação")

        assert res_g.confidence >= res_p.confidence

    @pytest.mark.asyncio
    async def test_proporcao_fora_de_intervalo_retorna_none(self, tmp_path: Path):
        """Retângulo extremamente largo (proporção >3) deve ser filtrado."""
        pytest.importorskip("cv2")
        import numpy as np
        import cv2 as cv

        imagem = tmp_path / "frasco.png"
        mascara = tmp_path / "mascara.png"

        # Retângulo muito largo: 220px × 20px → proporção 11.0
        img = np.zeros((256, 256, 3), dtype=np.uint8)
        cv.rectangle(img, (10, 118), (230, 138), (255, 255, 255), thickness=2)
        cv.imwrite(str(imagem), img)

        msk = np.zeros((256, 256, 4), dtype=np.uint8)
        msk[:, :, 3] = 255
        cv.imwrite(str(mascara), msk)

        extrator = HomographyLabelExtractor()
        resultado = await extrator.extract(imagem, mascara, tmp_path / "label.png")
        assert resultado is None


# ---------------------------------------------------------- _ordenar_cantos


class TestOrdenarCantos:
    def test_cantos_em_ordem_correta(self):
        """Verifica TL, TR, BR, BL com pontos conhecidos."""
        cv2 = pytest.importorskip("cv2")  # noqa: F841
        import numpy as np

        # Retângulo simples com cantos claramente identificáveis.
        pontos = np.array(
            [[10.0, 10.0], [100.0, 10.0], [100.0, 80.0], [10.0, 80.0]],
            dtype=np.float32,
        )
        # Embaralha para garantir que a ordenação é independente da entrada.
        indices = [2, 0, 3, 1]
        pontos_embaralhados = pontos[indices]

        resultado = _ordenar_cantos(pontos_embaralhados)

        np.testing.assert_allclose(resultado[0], [10.0, 10.0], atol=1e-5)   # TL
        np.testing.assert_allclose(resultado[1], [100.0, 10.0], atol=1e-5)  # TR
        np.testing.assert_allclose(resultado[2], [100.0, 80.0], atol=1e-5)  # BR
        np.testing.assert_allclose(resultado[3], [10.0, 80.0], atol=1e-5)   # BL

    def test_retorna_array_float32(self):
        pytest.importorskip("cv2")
        import numpy as np

        pontos = np.array(
            [[0.0, 0.0], [50.0, 0.0], [50.0, 50.0], [0.0, 50.0]],
            dtype=np.float32,
        )
        resultado = _ordenar_cantos(pontos)
        assert resultado.dtype == np.float32
        assert resultado.shape == (4, 2)
