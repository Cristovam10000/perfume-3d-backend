"""Testes do matte da label: separar o texto do vidro fotografado em volta."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.modules.captures.label_matte import (
    BackgroundSubtractionLabelMatte,
    DisabledLabelMatte,
)


def _label_sintetica(
    destino: Path, lado: int = 256, com_gradiente: bool = True
) -> Path:
    """Recorte parecido com o real: texto claro sobre vidro, com gradiente.

    O gradiente e o ponto do teste. No recorte real do job 3a3adbc8 ele tem
    amplitude MAIOR que a diferenca texto/fundo, entao um limiar global acerta o
    canto claro e erra o escuro. So a subtracao de fundo separa os dois.
    """
    yy, xx = np.mgrid[0:lado, 0:lado]
    fundo = 100.0 + 40.0 * (xx / lado)  # varia 100 -> 140 da esquerda p/ direita
    img = fundo.copy()
    # Duas barras de "texto", uma no lado escuro e outra no lado claro, ambas
    # apenas ~25 acima da vizinhanca imediata.
    img[40:60, 20:100] += 25.0
    img[180:200, 160:240] += 25.0
    if not com_gradiente:
        img = img - fundo + 120.0
    arr = np.clip(img, 0, 255).astype(np.uint8)
    Image.fromarray(np.dstack([arr] * 3), mode="RGB").save(destino)
    return destino


class TestDisabledLabelMatte:
    @pytest.mark.asyncio
    async def test_copia_sem_criar_alpha(self, tmp_path: Path):
        entrada = _label_sintetica(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await DisabledLabelMatte().aplicar(entrada, saida)

        assert saida.exists()
        assert "A" not in Image.open(saida).getbands()

    @pytest.mark.asyncio
    async def test_entrada_ausente_levanta(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await DisabledLabelMatte().aplicar(
                tmp_path / "nao_existe.png", tmp_path / "out.png"
            )


class TestBackgroundSubtractionLabelMatte:
    @pytest.mark.asyncio
    async def test_gera_rgba_com_fundo_transparente(self, tmp_path: Path):
        entrada = _label_sintetica(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await BackgroundSubtractionLabelMatte().aplicar(entrada, saida)

        img = Image.open(saida)
        assert img.mode == "RGBA"
        alpha = np.asarray(img.getchannel("A"))
        # O grosso da area e vidro e tem de sair transparente.
        assert (alpha < 10).mean() > 0.80

    @pytest.mark.asyncio
    async def test_texto_sobrevive_dos_dois_lados_do_gradiente(self, tmp_path: Path):
        """A barra do lado escuro e a do lado claro precisam virar tinta.

        E o caso que derruba limiar global: no recorte real o gradiente de
        iluminacao (~29) supera a separacao texto/fundo (~24).
        """
        entrada = _label_sintetica(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await BackgroundSubtractionLabelMatte().aplicar(entrada, saida)

        alpha = np.asarray(Image.open(saida).getchannel("A"), dtype=np.float32)
        barra_escura = alpha[45:55, 30:90].mean()
        barra_clara = alpha[185:195, 170:230].mean()

        assert barra_escura > 128, f"barra no lado escuro sumiu ({barra_escura:.0f})"
        assert barra_clara > 128, f"barra no lado claro sumiu ({barra_clara:.0f})"

    @pytest.mark.asyncio
    async def test_preserva_dimensoes(self, tmp_path: Path):
        entrada = _label_sintetica(tmp_path / "in.png", lado=192)
        saida = tmp_path / "out.png"

        await BackgroundSubtractionLabelMatte().aplicar(entrada, saida)

        assert Image.open(saida).size == (192, 192)

    @pytest.mark.asyncio
    async def test_forcar_branco_desligado_mantem_a_cor_original(
        self, tmp_path: Path
    ):
        entrada = _label_sintetica(tmp_path / "in.png")
        saida = tmp_path / "out.png"

        await BackgroundSubtractionLabelMatte(forcar_branco=False).aplicar(
            entrada, saida
        )

        rgb = np.asarray(Image.open(saida).convert("RGB"), dtype=np.float32)
        # Sem o empurrao para branco, a tinta continua no cinza da foto.
        assert rgb[45:55, 30:90].mean() < 200

    @pytest.mark.asyncio
    async def test_entrada_ausente_levanta(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await BackgroundSubtractionLabelMatte().aplicar(
                tmp_path / "nao_existe.png", tmp_path / "out.png"
            )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"raio_fundo": 0.0},
            {"raio_fundo": 1.0},
            {"piso": -1.0},
            {"piso": 20.0, "ganho": 10.0},
        ],
    )
    def test_parametros_invalidos_levantam(self, kwargs):
        with pytest.raises(ValueError):
            BackgroundSubtractionLabelMatte(**kwargs)
