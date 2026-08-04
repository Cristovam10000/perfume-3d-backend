"""Testes da guarda de foto de topo.

A guarda existe porque o `TopProjector` estica a foto inteira sobre as faces da
tampa sem procurar a tampa dentro dela: uma foto obliqua do frasco nao gera erro
nenhum, so um modelo errado. Ver `app/modules/captures/top_photo_check.py`.

Os valores de referencia vieram das 34 fotos reais dos jobs do projeto:
topo correto 1,03 / topo obliquo 2,06 / cardeais 1,50–4,23.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.modules.captures.top_photo_check import (
    checar_foto_de_topo,
    elongacao_da_mascara,
)


# ----------------------------------------------------------------- helpers


def mascara_retangulo(largura: int, altura: int, lado: int = 200) -> np.ndarray:
    grade = np.zeros((lado, lado), dtype=bool)
    y0 = (lado - altura) // 2
    x0 = (lado - largura) // 2
    grade[y0 : y0 + altura, x0 : x0 + largura] = True
    return grade


def mascara_circulo(raio: int, lado: int = 200) -> np.ndarray:
    ys, xs = np.ogrid[:lado, :lado]
    centro = lado // 2
    return (xs - centro) ** 2 + (ys - centro) ** 2 <= raio**2


def girar(mascara: np.ndarray, graus: float) -> np.ndarray:
    img = Image.fromarray((mascara * 255).astype(np.uint8))
    return np.array(img.rotate(graus, resample=Image.NEAREST, expand=True)) > 127


# ------------------------------------------------------------ elongacao


def test_circulo_tem_elongacao_proxima_de_um():
    assert elongacao_da_mascara(mascara_circulo(60)) == pytest.approx(1.0, abs=0.05)


def test_quadrado_tem_elongacao_proxima_de_um():
    assert elongacao_da_mascara(mascara_retangulo(80, 80)) == pytest.approx(
        1.0, abs=0.05
    )


def test_retangulo_3x1_tem_elongacao_proxima_de_tres():
    assert elongacao_da_mascara(mascara_retangulo(40, 120)) == pytest.approx(
        3.0, abs=0.15
    )


def test_elongacao_independe_da_orientacao():
    """Deitado ou em pe, a mesma forma tem a mesma elongacao."""
    em_pe = elongacao_da_mascara(mascara_retangulo(40, 120))
    deitado = elongacao_da_mascara(mascara_retangulo(120, 40))
    assert em_pe == pytest.approx(deitado, abs=0.05)


def test_elongacao_e_invariante_a_rotacao():
    """É por isso que usamos PCA e não a razão da bounding box.

    Um retângulo 3:1 girado 45° tem bounding box quase quadrada — a razão da
    bbox cairia para perto de 1,0 e uma foto de perfil enquadrada torta passaria
    batido. Os eixos principais continuam denunciando a elongação real.
    """
    reto = mascara_retangulo(40, 120)
    torto = girar(reto, 45.0)

    assert elongacao_da_mascara(reto) == pytest.approx(
        elongacao_da_mascara(torto), abs=0.2
    )

    # E a bbox realmente engana, o que justifica a escolha:
    ys, xs = np.nonzero(torto)
    razao_bbox = (ys.max() - ys.min() + 1) / (xs.max() - xs.min() + 1)
    assert razao_bbox == pytest.approx(1.0, abs=0.1)


def test_mascara_vazia_devolve_nan():
    assert math.isnan(elongacao_da_mascara(np.zeros((50, 50), dtype=bool)))


def test_mascara_minuscula_devolve_nan():
    """Poucos pixels nao dao covariancia significativa."""
    grade = np.zeros((50, 50), dtype=bool)
    grade[10:13, 10:13] = True  # 9 pixels
    assert math.isnan(elongacao_da_mascara(grade))


# ------------------------------------------------------------- veredito


def _salvar(mascara: np.ndarray, destino: Path) -> Path:
    rgba = np.zeros((*mascara.shape, 4), dtype=np.uint8)
    rgba[..., :3] = 200
    rgba[..., 3] = mascara * 255
    destino.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(destino)
    return destino


def test_silhueta_compacta_e_aprovada(tmp_path: Path):
    caminho = _salvar(mascara_circulo(70), tmp_path / "topo.png")
    veredito = checar_foto_de_topo(caminho)
    assert veredito.aprovado
    assert veredito.elongacao == pytest.approx(1.0, abs=0.05)


def test_silhueta_alongada_e_reprovada(tmp_path: Path):
    caminho = _salvar(mascara_retangulo(40, 140), tmp_path / "perfil.png")
    veredito = checar_foto_de_topo(caminho)
    assert not veredito.aprovado
    assert veredito.elongacao > 1.35
    assert "elongação" in veredito.motivo


def test_limite_e_configuravel(tmp_path: Path):
    caminho = _salvar(mascara_retangulo(60, 120), tmp_path / "meio.png")
    assert not checar_foto_de_topo(caminho, limite=1.35).aprovado
    assert checar_foto_de_topo(caminho, limite=3.0).aprovado


def test_arquivo_ilegivel_aprova(tmp_path: Path):
    """Falha ao medir nao pode virar perda silenciosa de funcionalidade.

    A guarda protege contra foto obliqua; nao e um validador de arquivo.
    """
    caminho = tmp_path / "quebrado.png"
    caminho.write_bytes(b"isto nao e um png")
    veredito = checar_foto_de_topo(caminho)
    assert veredito.aprovado
    assert "não foi possível abrir" in veredito.motivo


def test_imagem_totalmente_transparente_aprova(tmp_path: Path):
    caminho = _salvar(np.zeros((80, 80), dtype=bool), tmp_path / "vazia.png")
    veredito = checar_foto_de_topo(caminho)
    assert veredito.aprovado
    assert "pequena demais" in veredito.motivo
