"""Testes da heuristica de segmentacao corpo/tampa.

`segment_bottle.py` roda dentro do Blender, mas `encontrar_corte` e Python
puro (recebe lista de alturas, devolve o corte). Para testa-la sem Blender,
injetamos um stub de `bpy` em `sys.modules` antes de importar o modulo.

Cobertura:
- pico de densidade detectado na faixa de busca;
- pico fora da faixa (topo/fundo do frasco) ignorado;
- perfil uniforme rejeitado (razao abaixo do minimo);
- entradas degeneradas nao explodem.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACK_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    BACK_ROOT
    / "app"
    / "modules"
    / "captures"
    / "blender_scripts"
    / "segment_bottle.py"
)


def _carregar_modulo():
    """Importa segment_bottle com `bpy` e `mathutils` stubados."""
    for nome in ("bpy", "mathutils"):
        if nome not in sys.modules:
            sys.modules[nome] = types.ModuleType(nome)

    spec = importlib.util.spec_from_file_location("segment_bottle_sob_teste", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


segment_bottle = _carregar_modulo()


def _perfil(contagens: list[int]) -> list[float]:
    """Constroi alturas cujo histograma reproduz `contagens`.

    Cada fatia i recebe `contagens[i]` alturas dentro da sua faixa, de modo que
    `encontrar_corte` veja exatamente o histograma desejado.
    """
    n = len(contagens)
    zs: list[float] = []
    for i, qtd in enumerate(contagens):
        centro = (i + 0.5) / n
        zs.extend([centro] * qtd)
    # Ancora os extremos para que z_min=0 e z_max=1 e as fatias batam.
    zs.extend([0.0, 1.0])
    return zs


class TestEncontrarCorte:
    def test_detecta_pico_dentro_da_faixa(self):
        # 24 fatias; pico na fatia 16 (z_rel 0.67), como GRAND e Vivacite.
        contagens = [20] * 24
        contagens[16] = 48
        z_corte, diag = segment_bottle.encontrar_corte(_perfil(contagens))

        assert z_corte is not None
        assert diag["z_rel_pico"] == pytest.approx(16 / 24, abs=1e-6)
        assert diag["razao"] == pytest.approx(48 / 20, rel=0.2)

    def test_pico_no_topo_e_ignorado(self):
        # A face superior da tampa tambem concentra faces, mas fica fora da
        # faixa de busca — nao pode virar o corte.
        contagens = [20] * 24
        contagens[23] = 200  # topo do frasco
        contagens[18] = 40   # ombro real, dentro da faixa
        z_corte, diag = segment_bottle.encontrar_corte(_perfil(contagens))

        assert z_corte is not None
        assert diag["z_rel_pico"] == pytest.approx(18 / 24, abs=1e-6)

    def test_pico_no_fundo_e_ignorado(self):
        contagens = [20] * 24
        contagens[0] = 300  # fundo do frasco
        contagens[15] = 45
        _z, diag = segment_bottle.encontrar_corte(_perfil(contagens))

        assert diag["z_rel_pico"] == pytest.approx(15 / 24, abs=1e-6)

    def test_perfil_uniforme_e_rejeitado(self):
        # Sem ombro discernivel a segmentacao deve abortar em vez de cortar
        # num ponto arbitrario.
        z_corte, diag = segment_bottle.encontrar_corte(_perfil([20] * 24))

        assert z_corte is None
        assert "razao" in diag["motivo"]

    def test_razao_no_limite_e_rejeitada(self):
        contagens = [20] * 24
        contagens[16] = int(20 * segment_bottle.RAZAO_MINIMA) - 1
        z_corte, _diag = segment_bottle.encontrar_corte(_perfil(contagens))

        assert z_corte is None

    def test_corte_fica_acima_do_pico(self):
        """O ombro pertence ao corpo; o corte vai no topo da fatia do pico."""
        contagens = [20] * 24
        contagens[16] = 60
        z_corte, _diag = segment_bottle.encontrar_corte(_perfil(contagens))

        assert z_corte == pytest.approx(17 / 24, abs=1e-6)

    def test_mesh_degenerado_nao_explode(self):
        z_corte, diag = segment_bottle.encontrar_corte([0.5] * 100)

        assert z_corte is None
        assert "degenerado" in diag["motivo"]


class TestConstantesCalibradas:
    """Trava os valores medidos nos GLBs reais (ver docstring do script)."""

    def test_faixa_de_busca_exclui_extremos(self):
        assert 0.0 < segment_bottle.Z_MIN_BUSCA < segment_bottle.Z_MAX_BUSCA < 1.0

    def test_razao_minima_abaixo_dos_frascos_medidos(self):
        # GRAND 2.11x, Vivacite 2.22x, ASAD 2.28x — o limiar precisa aceitar
        # os tres com folga e ainda barrar perfis planos.
        assert 1.0 < segment_bottle.RAZAO_MINIMA <= 2.0

    def test_slots_de_material_sao_distintos(self):
        assert segment_bottle.MATERIAL_CORPO != segment_bottle.MATERIAL_TAMPA
