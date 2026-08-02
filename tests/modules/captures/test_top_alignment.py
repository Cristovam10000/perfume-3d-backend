"""Testes da estimativa de rotacao do topo por silhueta.

`top_alignment.py` e numpy puro (nao importa `bpy`), entao roda direto.

A estrategia e gerar silhuetas sinteticas com rotacao **conhecida** e verificar
que o estimador recupera o angulo. Cobre tambem os dois casos degenerados que
importam na pratica: tampa circular (rotacao indeterminada) e mascara vazia.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

BACK_ROOT = Path(__file__).resolve().parents[3]
MODULO = (
    BACK_ROOT
    / "app"
    / "modules"
    / "captures"
    / "blender_scripts"
    / "top_alignment.py"
)

_NOME = "top_alignment_sob_teste"
spec = importlib.util.spec_from_file_location(_NOME, MODULO)
top_alignment = importlib.util.module_from_spec(spec)
# `@dataclass` resolve anotacoes via `sys.modules[cls.__module__]`; sem registrar
# antes do exec, a criacao da dataclass estoura AttributeError.
sys.modules[_NOME] = top_alignment
spec.loader.exec_module(top_alignment)


# ------------------------------------------------------------------ helpers


def _poligono(n_lados: int, tamanho: int = 120, rotacao_graus: float = 0.0) -> np.ndarray:
    """Mascara booleana de um poligono regular, opcionalmente girado."""
    centro = tamanho / 2.0
    raio = tamanho * 0.38
    rad = np.radians(rotacao_graus)

    cantos = [
        (
            centro + raio * np.cos(2 * np.pi * i / n_lados + rad),
            centro + raio * np.sin(2 * np.pi * i / n_lados + rad),
        )
        for i in range(n_lados)
    ]

    ys, xs = np.mgrid[0:tamanho, 0:tamanho]
    dentro = np.ones((tamanho, tamanho), dtype=bool)
    for i in range(n_lados):
        x1, y1 = cantos[i]
        x2, y2 = cantos[(i + 1) % n_lados]
        # Lado esquerdo da aresta (poligono e convexo e os cantos vao no sentido
        # anti-horario, entao "dentro" e o mesmo lado para todas as arestas).
        dentro &= ((x2 - x1) * (ys - y1) - (y2 - y1) * (xs - x1)) >= 0
    return dentro


def _ele(tamanho: int = 120) -> np.ndarray:
    """Forma em "L" de braços **desiguais** — quiral de verdade.

    Necessária para testar espelhamento, e a desigualdade importa:

    - Um polígono regular espelhado é idêntico a ele rotacionado (simetria
      diedral).
    - Um "L" de braços **iguais** tem simetria de reflexão na diagonal, então
      espelhá-lo também equivale a girá-lo 270°.

    Só com braços de comprimentos diferentes nenhuma rotação reproduz o espelho.
    """
    m = np.zeros((tamanho, tamanho), dtype=bool)
    q = tamanho // 4
    espessura = q // 2
    m[q : 3 * q, q : q + espessura] = True        # haste longa (2q)
    m[q : q + espessura, q : 2 * q] = True        # pé curto (q)
    return m


def _girar_mascara(mascara: np.ndarray, graus: float) -> np.ndarray:
    """Gira uma máscara booleana em torno do centro (vizinho mais próximo)."""
    tamanho = mascara.shape[0]
    centro = (tamanho - 1) / 2.0
    ys, xs = np.mgrid[0:tamanho, 0:tamanho]
    rad = np.radians(-graus)
    cos, sen = np.cos(rad), np.sin(rad)
    ox, oy = xs - centro, ys - centro
    sx = np.rint(ox * cos - oy * sen + centro).astype(int)
    sy = np.rint(ox * sen + oy * cos + centro).astype(int)
    valido = (sx >= 0) & (sx < tamanho) & (sy >= 0) & (sy < tamanho)
    saida = np.zeros_like(mascara)
    saida[valido] = mascara[sy[valido], sx[valido]]
    return saida


def _circulo(tamanho: int = 120) -> np.ndarray:
    centro = tamanho / 2.0
    ys, xs = np.mgrid[0:tamanho, 0:tamanho]
    return ((xs - centro) ** 2 + (ys - centro) ** 2) < (tamanho * 0.38) ** 2


def _erro_angular(estimado: float, esperado: float, simetria: int) -> float:
    """Menor diferenca considerando a simetria rotacional do poligono."""
    periodo = 360.0 / simetria
    delta = abs(estimado - esperado) % periodo
    return min(delta, periodo - delta)


# ------------------------------------------------------------------ testes


class TestRecuperaAngulo:
    @pytest.mark.parametrize("angulo", [0.0, 30.0, 75.0, 140.0, 250.0])
    def test_triangulo(self, angulo: float):
        """Triangulo é o caso do Lattafa ASAD — silhueta bem assimétrica."""
        modelo = _poligono(3)
        foto = _poligono(3, rotacao_graus=angulo)

        r = top_alignment.estimar_rotacao(modelo, foto, permitir_espelho=False)

        assert r is not None
        # O estimador gira a foto DE VOLTA, então o ângulo é o complemento.
        assert _erro_angular(r.angulo_graus, -angulo, simetria=3) <= 4.0
        assert r.iou > 0.85

    @pytest.mark.parametrize("angulo", [15.0, 60.0])
    def test_quadrado(self, angulo: float):
        modelo = _poligono(4)
        foto = _poligono(4, rotacao_graus=angulo)

        r = top_alignment.estimar_rotacao(modelo, foto, permitir_espelho=False)

        assert r is not None
        assert _erro_angular(r.angulo_graus, -angulo, simetria=4) <= 4.0

    def test_invariante_a_escala(self):
        """Foto e malha têm tamanhos diferentes; a normalização deve absorver."""
        modelo = _poligono(3, tamanho=200)
        foto = _poligono(3, tamanho=80, rotacao_graus=45.0)

        r = top_alignment.estimar_rotacao(modelo, foto, permitir_espelho=False)

        assert r is not None
        assert _erro_angular(r.angulo_graus, -45.0, simetria=3) <= 6.0


class TestConfianca:
    def test_circulo_e_ambiguo(self):
        """Girar um círculo não muda a silhueta — o estimador deve admitir isso."""
        r = top_alignment.estimar_rotacao(_circulo(), _circulo())

        assert r is not None
        assert r.iou > 0.9          # encaixa bem em qualquer ângulo
        assert not r.confiavel      # ...e justamente por isso não é confiável
        assert r.confianca < 1.08

    def test_triangulo_e_confiavel(self):
        r = top_alignment.estimar_rotacao(
            _poligono(3), _poligono(3, rotacao_graus=90.0), permitir_espelho=False
        )

        assert r is not None
        assert r.confiavel
        assert r.confianca > 1.08


class TestEspelhamento:
    def test_detecta_espelho_em_forma_quiral(self):
        """Só uma forma sem simetria de reflexão consegue distinguir espelho."""
        modelo = _ele()
        foto = _ele()[:, ::-1]  # espelhado em X

        r = top_alignment.estimar_rotacao(modelo, foto, permitir_espelho=True)

        assert r is not None
        assert r.espelhar
        assert r.iou > 0.75

    def test_nao_espelha_quando_nao_precisa(self):
        modelo = _ele()
        foto = _girar_mascara(_ele(), 30.0)

        r = top_alignment.estimar_rotacao(modelo, foto, permitir_espelho=True)

        assert r is not None
        assert not r.espelhar

    def test_poligono_regular_nao_serve_para_detectar_espelho(self):
        """Documenta a limitação: espelhar um triângulo regular = rotacioná-lo.

        Por isso `permitir_espelho` fica **desligado** na chamada de produção —
        num frasco quase simétrico o espelho seria escolhido por ruído e
        produziria um logo invertido, pior que um logo girado.
        """
        r = top_alignment.estimar_rotacao(
            _poligono(3), _poligono(3, rotacao_graus=20.0)[:, ::-1],
            permitir_espelho=True,
        )

        assert r is not None
        assert not r.espelhar   # resolveu por rotação pura
        assert r.iou > 0.85


class TestDegenerados:
    def test_mascara_vazia(self):
        vazia = np.zeros((60, 60), dtype=bool)
        assert top_alignment.estimar_rotacao(_poligono(3), vazia) is None

    def test_poucos_pontos(self):
        quase_vazia = np.zeros((60, 60), dtype=bool)
        quase_vazia[10:12, 10:12] = True  # 4 pontos, abaixo do mínimo
        assert top_alignment.estimar_rotacao(_poligono(3), quase_vazia) is None

    def test_ambas_vazias(self):
        vazia = np.zeros((60, 60), dtype=bool)
        assert top_alignment.estimar_rotacao(vazia, vazia) is None
