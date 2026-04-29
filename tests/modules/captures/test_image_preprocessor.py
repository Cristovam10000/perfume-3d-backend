"""Testes do ImagePreprocessor.

Estratégia:
- DisabledImagePreprocessor: testes diretos sem dependências.
- StandardImagePreprocessor: usa cv2/numpy quando disponíveis (importorskip).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.image_preprocessor import (
    DisabledImagePreprocessor,
    ImagePreprocessor,
    StandardImagePreprocessor,
)


# ---------------------------------------------------------- helpers de fixtures


def _make_solid_png(path: Path, color: tuple[int, int, int], size: int = 64) -> None:
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


def _save_pil_jpeg_with_exif(
    path: Path, *, width: int, height: int, exif_orientation: int, color: tuple[int, int, int]
) -> None:
    """Cria JPEG com tag EXIF de orientação (1..8)."""
    Image = pytest.importorskip("PIL.Image")
    from PIL import Image as PILImage  # type: ignore  # noqa: F401

    imagem = PILImage.new("RGB", (width, height), color)

    # Tag 0x0112 = Orientation. Pillow expõe via getexif().
    exif = imagem.getexif()
    exif[0x0112] = exif_orientation
    imagem.save(path, format="JPEG", exif=exif.tobytes(), quality=95)


# ---------------------------------------------------------- DisabledImagePreprocessor


class TestDisabledImagePreprocessor:
    def test_is_image_preprocessor_subclass(self):
        assert issubclass(DisabledImagePreprocessor, ImagePreprocessor)

    @pytest.mark.asyncio
    async def test_copia_byte_a_byte(self, tmp_path: Path):
        entrada = tmp_path / "frasco.png"
        saida = tmp_path / "out.png"
        _make_solid_png(entrada, color=(120, 80, 40))

        preproc = DisabledImagePreprocessor()
        resultado = await preproc.preprocess(entrada, saida)

        assert resultado == saida
        assert saida.exists()
        assert saida.read_bytes() == entrada.read_bytes()

    @pytest.mark.asyncio
    async def test_cria_diretorio_pai(self, tmp_path: Path):
        entrada = tmp_path / "frasco.png"
        saida = tmp_path / "subdir" / "out.png"
        _make_solid_png(entrada, color=(0, 0, 255))

        preproc = DisabledImagePreprocessor()
        await preproc.preprocess(entrada, saida)

        assert saida.exists()

    @pytest.mark.asyncio
    async def test_arquivo_inexistente_levanta_file_not_found(self, tmp_path: Path):
        preproc = DisabledImagePreprocessor()
        with pytest.raises(FileNotFoundError):
            await preproc.preprocess(tmp_path / "nao.png", tmp_path / "out.png")


# ---------------------------------------------------------- StandardImagePreprocessor


class TestStandardImagePreprocessor:
    def test_is_image_preprocessor_subclass(self):
        assert issubclass(StandardImagePreprocessor, ImagePreprocessor)

    def test_parametros_invalidos_levantam_value_error(self):
        with pytest.raises(ValueError):
            StandardImagePreprocessor(clahe_clip_limit=0.0)
        with pytest.raises(ValueError):
            StandardImagePreprocessor(sharpen_threshold=-1.0)
        with pytest.raises(ValueError):
            StandardImagePreprocessor(max_resolution=0)

    @pytest.mark.asyncio
    async def test_arquivo_inexistente_levanta_file_not_found(self, tmp_path: Path):
        pytest.importorskip("cv2")
        preproc = StandardImagePreprocessor()
        with pytest.raises(FileNotFoundError):
            await preproc.preprocess(tmp_path / "nao.png", tmp_path / "out.png")

    @pytest.mark.asyncio
    async def test_exif_orientation_corrected(self, tmp_path: Path):
        """JPEG com orientation=6 (rotacionada 90°) deve sair com dimensões trocadas."""
        pytest.importorskip("cv2")
        Image = pytest.importorskip("PIL.Image")
        from PIL import Image as PILImage

        entrada = tmp_path / "rot.jpg"
        saida = tmp_path / "out.jpg"
        # Cria 200×100 com orientation=6 → após exif_transpose vira 100×200.
        _save_pil_jpeg_with_exif(
            entrada, width=200, height=100, exif_orientation=6, color=(180, 180, 180)
        )

        preproc = StandardImagePreprocessor(max_resolution=4096)
        await preproc.preprocess(entrada, saida)

        with PILImage.open(saida) as img_out:
            largura_out, altura_out = img_out.size

        # Após orientation=6 (rotação 90° CW), largura e altura trocam.
        assert (largura_out, altura_out) == (100, 200)

    @pytest.mark.asyncio
    async def test_white_balance_neutralizes_color_cast(self, tmp_path: Path):
        """Imagem com tinte amarelo deve sair com canais R,G,B mais próximos."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "amarela.png"
        saida = tmp_path / "out.png"

        # Imagem 64×64 com tinte amarelo claro: R=200, G=200, B=80.
        # Em BGR (cv2), isso é (B=80, G=200, R=200).
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:, :, 0] = 80   # B
        img[:, :, 1] = 200  # G
        img[:, :, 2] = 200  # R
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=True,
            clahe_clip_limit=0.01,  # CLAHE praticamente desligado para isolar o efeito do WB
            sharpen_threshold=0.0,  # nunca sharpen
            max_resolution=4096,
        )
        await preproc.preprocess(entrada, saida)

        saida_img = cv2.imread(str(saida))
        assert saida_img is not None
        medias = saida_img.reshape(-1, 3).mean(axis=0)
        # Em uma imagem uniformemente colorida, gray-world força os 3 canais
        # a convergirem para a média global. Tolerância larga porque CLAHE
        # mexe levemente nas médias.
        assert max(medias) - min(medias) < 30, (
            f"WB falhou: canais ainda muito desbalanceados (medias={medias})"
        )

    @pytest.mark.asyncio
    async def test_clahe_increases_contrast_on_underexposed(self, tmp_path: Path):
        """Imagem cinza escura quase uniforme tem stdv baixo; após CLAHE deve aumentar."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "escura.png"
        saida = tmp_path / "out.png"

        # Imagem 256×256 com gradiente leve de cinza escuro (média ~50, stdv ~7).
        img = np.zeros((256, 256, 3), dtype=np.uint8)
        for y in range(256):
            valor = 45 + (y // 32)  # 45..52
            img[y, :, :] = valor
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False,  # foca só no efeito do CLAHE
            clahe_clip_limit=4.0,
            sharpen_threshold=0.0,
            max_resolution=4096,
        )
        await preproc.preprocess(entrada, saida)

        # Calcula stdv do canal L do LAB antes/depois.
        antes_lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        depois = cv2.imread(str(saida))
        depois_lab = cv2.cvtColor(depois, cv2.COLOR_BGR2LAB)

        std_antes = float(antes_lab[:, :, 0].std())
        std_depois = float(depois_lab[:, :, 0].std())

        assert std_depois > std_antes, (
            f"CLAHE não aumentou contraste: std antes={std_antes:.2f}, "
            f"depois={std_depois:.2f}"
        )

    @pytest.mark.asyncio
    async def test_sharpen_skipped_when_image_already_sharp(self, tmp_path: Path):
        """Quando Laplacian variance > threshold, addWeighted NÃO deve ser chamado."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "nitida.png"
        saida = tmp_path / "out.png"

        # Imagem com bordas pretas e brancas → Laplacian variance alta.
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[16:48, 16:48] = 255
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False,
            sharpen_threshold=10.0,  # baixa, fácil de superar
            max_resolution=4096,
        )

        # Usa side_effect=cv2.addWeighted real só pra contar chamadas.
        addweighted_real = cv2.addWeighted
        # Array com variância alta (alterna 0 e 2000) — Laplacian.var() = 1e6.
        laplacian_fake = np.array([0.0, 2000.0] * 50, dtype=np.float64).reshape(10, 10)
        with patch(
            "cv2.addWeighted", side_effect=addweighted_real
        ) as mock_addweighted, patch(
            "cv2.Laplacian", return_value=laplacian_fake
        ):
            await preproc.preprocess(entrada, saida)

        assert mock_addweighted.call_count == 0, (
            "addWeighted (unsharp) não deveria ter sido chamado para imagem nítida"
        )

    @pytest.mark.asyncio
    async def test_resize_caps_at_max_resolution(self, tmp_path: Path):
        """Input 4096×3072 deve sair com lado maior = 2048."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "grande.png"
        saida = tmp_path / "out.png"

        img = np.zeros((3072, 4096, 3), dtype=np.uint8)
        img[:, :, 1] = 128  # canal verde, evita imagem totalmente preta
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False,
            sharpen_threshold=0.0,
            max_resolution=2048,
        )
        await preproc.preprocess(entrada, saida)

        saida_img = cv2.imread(str(saida))
        altura, largura = saida_img.shape[:2]
        assert max(altura, largura) == 2048
        # 4096:3072 = 4:3 → 2048:1536
        assert (largura, altura) == (2048, 1536)

    @pytest.mark.asyncio
    async def test_aspect_ratio_preserved(self, tmp_path: Path):
        """Aspect ratio do input deve ser preservada no output (tolerância 1px)."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "estreita.png"
        saida = tmp_path / "out.png"

        # 3000×1000 → 16:9... na verdade 3:1.
        img = np.zeros((1000, 3000, 3), dtype=np.uint8)
        img[:, :, 2] = 200
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False,
            sharpen_threshold=0.0,
            max_resolution=2048,
        )
        await preproc.preprocess(entrada, saida)

        saida_img = cv2.imread(str(saida))
        altura, largura = saida_img.shape[:2]
        # Razão original = 3.0; tolerância pequena.
        razao = largura / altura
        assert abs(razao - 3.0) < 0.05, f"aspect ratio fugiu: {razao:.3f}"

    @pytest.mark.asyncio
    async def test_resize_skipped_when_below_max(self, tmp_path: Path):
        """Imagem pequena não deve ser ampliada nem reduzida."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "pequena.png"
        saida = tmp_path / "out.png"

        img = np.zeros((400, 600, 3), dtype=np.uint8)
        img[:, :, 0] = 128
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False,
            sharpen_threshold=0.0,
            max_resolution=2048,
        )
        await preproc.preprocess(entrada, saida)

        saida_img = cv2.imread(str(saida))
        altura, largura = saida_img.shape[:2]
        assert (largura, altura) == (600, 400)

    @pytest.mark.asyncio
    async def test_jpeg_output_uses_quality_95(self, tmp_path: Path):
        """Quando a saída é .jpg, deve gravar com qualidade 95 (chamada cv2.imwrite com flag)."""
        cv2 = pytest.importorskip("cv2")
        import numpy as np

        entrada = tmp_path / "in.png"
        saida = tmp_path / "out.jpg"

        img = np.full((64, 64, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(entrada), img)

        preproc = StandardImagePreprocessor(
            white_balance=False, sharpen_threshold=0.0, max_resolution=4096
        )

        imwrite_real = cv2.imwrite
        chamadas: list[tuple] = []

        def spy_imwrite(path, image, params=None):
            chamadas.append((path, params))
            if params is None:
                return imwrite_real(path, image)
            return imwrite_real(path, image, params)

        with patch("cv2.imwrite", side_effect=spy_imwrite):
            await preproc.preprocess(entrada, saida)

        assert any(
            str(saida) == str(p) and params is not None and 95 in params
            for p, params in chamadas
        ), f"imwrite não recebeu IMWRITE_JPEG_QUALITY=95 ({chamadas})"
