"""Testes do apagador de label na foto de referencia do gerador 3D."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.modules.captures.label_eraser import (
    DisabledLabelEraser,
    InpaintLabelEraser,
)

# Caixa em pixels (x, y, w, h) cobrindo o quarto central de uma foto 256x256,
# que e o tamanho usado por `_foto_com_texto`.
CAIXA = (96, 96, 64, 64)


def _foto_com_texto(destino: Path, lado: int = 256, alpha: bool = True) -> Path:
    """Foto sintetica: fundo suave + barras claras no centro fazendo de 'texto'."""
    yy, xx = np.mgrid[0:lado, 0:lado]
    base = 110.0 + 25.0 * (xx / lado)
    img = base.copy()
    c0, c1 = int(lado * 0.375), int(lado * 0.625)
    img[c0 + 10 : c0 + 22, c0 + 8 : c1 - 8] += 45.0
    img[c0 + 38 : c0 + 50, c0 + 8 : c1 - 8] += 45.0
    arr = np.clip(img, 0, 255).astype(np.uint8)
    rgb = np.dstack([arr] * 3)
    if alpha:
        a = np.full((lado, lado), 255, np.uint8)
        a[:20, :] = 0  # faixa recortada pelo BackgroundRemover
        Image.fromarray(np.dstack([rgb, a]), "RGBA").save(destino)
    else:
        Image.fromarray(rgb, "RGB").save(destino)
    return destino


def _media_no_texto(caminho: Path, lado: int = 256) -> float:
    arr = np.asarray(Image.open(caminho).convert("L"), dtype=np.float32)
    c0 = int(lado * 0.375)
    return float(arr[c0 + 10 : c0 + 22, c0 + 8 : int(lado * 0.625) - 8].mean())


class TestDisabledLabelEraser:
    @pytest.mark.asyncio
    async def test_devolve_none_e_nao_grava(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        assert await DisabledLabelEraser().apagar(entrada, saida, CAIXA) is None
        assert not saida.exists()


class TestInpaintLabelEraser:
    @pytest.mark.asyncio
    async def test_apaga_o_texto_da_caixa(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        antes = _media_no_texto(entrada)
        assert await InpaintLabelEraser().apagar(entrada, saida, CAIXA) == saida
        depois = _media_no_texto(saida)

        # A barra clara tem de encostar no nivel do fundo em volta.
        assert depois < antes - 20, f"texto sobreviveu ({antes:.0f} -> {depois:.0f})"

    @pytest.mark.asyncio
    async def test_preserva_o_alpha_da_segmentacao(self, tmp_path: Path):
        """O inpaint mexe no RGB; desfazer o recorte do fundo seria regressao."""
        entrada = _foto_com_texto(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await InpaintLabelEraser().apagar(entrada, saida, CAIXA)

        a_in = np.asarray(Image.open(entrada).getchannel("A"))
        a_out = np.asarray(Image.open(saida).getchannel("A"))
        assert np.array_equal(a_in, a_out)

    @pytest.mark.asyncio
    async def test_nao_toca_fora_da_caixa(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await InpaintLabelEraser().apagar(entrada, saida, CAIXA)

        antes = np.asarray(Image.open(entrada).convert("RGB"), dtype=np.int16)
        depois = np.asarray(Image.open(saida).convert("RGB"), dtype=np.int16)
        # Margem de 18% da caixa: fora dela nada pode mudar.
        assert np.array_equal(antes[:40, :], depois[:40, :])
        assert np.array_equal(antes[-40:, :], depois[-40:, :])

    @pytest.mark.asyncio
    async def test_preserva_dimensoes(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png", lado=192)
        saida = tmp_path / "out.png"

        await InpaintLabelEraser().apagar(entrada, saida, (72, 72, 48, 48))

        assert Image.open(saida).size == (192, 192)

    @pytest.mark.asyncio
    async def test_caixa_malformada_devolve_none(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png")

        assert (
            await InpaintLabelEraser().apagar(entrada, tmp_path / "o.png", (1, 2))
            is None
        )

    @pytest.mark.asyncio
    async def test_caixa_degenerada_devolve_none(self, tmp_path: Path):
        entrada = _foto_com_texto(tmp_path / "in.png")

        assert (
            await InpaintLabelEraser().apagar(entrada, tmp_path / "o.png", (128, 128, 1, 1))
            is None
        )

    @pytest.mark.asyncio
    async def test_sem_texto_detectado_devolve_none(self, tmp_path: Path):
        """Foto lisa: nada a apagar, e o pipeline segue com a original."""
        Image.fromarray(
            np.full((128, 128, 3), 120, np.uint8), "RGB"
        ).save(tmp_path / "lisa.png")

        assert (
            await InpaintLabelEraser().apagar(
                tmp_path / "lisa.png", tmp_path / "o.png", CAIXA
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_entrada_ausente_levanta(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await InpaintLabelEraser().apagar(
                tmp_path / "nao_existe.png", tmp_path / "o.png", CAIXA
            )

    @pytest.mark.parametrize(
        "kwargs",
        [{"piso": 0}, {"raio_fundo": 0}, {"dilatacao": -1}, {"margem": 1.0}],
    )
    def test_parametros_invalidos_levantam(self, kwargs):
        with pytest.raises(ValueError):
            InpaintLabelEraser(**kwargs)
