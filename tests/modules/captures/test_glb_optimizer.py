"""Testes do GlbOptimizer (compressao Draco do GLB final).

O Blender real nao roda aqui — `_run_blender` e substituido por um fake, entao
o que se valida e o contrato do wrapper: argumentos montados, pre-condicoes e
traducao de falha em excecao.

O ganho de compressao em si foi medido rodando o script de verdade sobre o GLB
do job `15ef21e9`: 77,1 MB -> 13,9 MB (5,5x). Duas otimizacoes adicionais foram
testadas e descartadas por medicao — ver o docstring de `optimize_glb.py`.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.glb_optimizer import (
    BlenderGlbOptimizer,
    DisabledGlbOptimizer,
    GlbOptimizationError,
    GlbOptimizationInput,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "optimize_glb.py"
)


def _minimal_glb() -> bytes:
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    return struct.pack("<III", 0x46546C67, 2, total) + json_chunk + bin_chunk


@pytest.fixture
def entrada(tmp_path: Path) -> Path:
    caminho = tmp_path / "with_top.glb"
    caminho.write_bytes(_minimal_glb())
    return caminho


class TestDisabledGlbOptimizer:
    @pytest.mark.asyncio
    async def test_copia_sem_comprimir(self, tmp_path: Path, entrada: Path):
        saida = tmp_path / "out" / "final.glb"
        resultado = await DisabledGlbOptimizer().optimize(
            GlbOptimizationInput(input_glb=entrada, output_glb=saida)
        )
        assert resultado.output_glb == saida
        assert saida.read_bytes() == entrada.read_bytes()
        # Sem compressao, o fator e 1: o pipeline loga isso sem tratar como erro.
        assert resultado.fator == pytest.approx(1.0)


class TestBlenderGlbOptimizer:
    def _otimizador(self, tmp_path: Path) -> BlenderGlbOptimizer:
        blender = tmp_path / "blender.exe"
        blender.write_bytes(b"fake")
        return BlenderGlbOptimizer(
            blender_executable=blender, script_path=SCRIPT_PATH
        )

    @pytest.mark.asyncio
    async def test_monta_argumentos_com_quantizacao(self, tmp_path: Path, entrada: Path):
        saida = tmp_path / "final.glb"
        capturados: list[str] = []

        async def fake_run(args):
            capturados.extend(args)
            saida.write_bytes(b"glb-comprimido")
            return 0, b"", b""

        otimizador = self._otimizador(tmp_path)
        with patch.object(otimizador, "_run_blender", side_effect=fake_run):
            resultado = await otimizador.optimize(
                GlbOptimizationInput(
                    input_glb=entrada,
                    output_glb=saida,
                    position_quantization=12,
                    texcoord_quantization=10,
                )
            )

        assert "--background" in capturados
        assert str(SCRIPT_PATH) in capturados
        assert capturados[capturados.index("--position-quantization") + 1] == "12"
        assert capturados[capturados.index("--texcoord-quantization") + 1] == "10"
        assert resultado.output_glb == saida
        assert resultado.bytes_antes == len(_minimal_glb())
        assert resultado.bytes_depois == len(b"glb-comprimido")

    @pytest.mark.asyncio
    async def test_retorno_diferente_de_zero_vira_excecao(
        self, tmp_path: Path, entrada: Path
    ):
        async def fake_run(args):
            return 1, b"", b"draco indisponivel"

        otimizador = self._otimizador(tmp_path)
        with patch.object(otimizador, "_run_blender", side_effect=fake_run):
            with pytest.raises(GlbOptimizationError, match="retornou 1"):
                await otimizador.optimize(
                    GlbOptimizationInput(
                        input_glb=entrada, output_glb=tmp_path / "f.glb"
                    )
                )

    @pytest.mark.asyncio
    async def test_saida_ausente_vira_excecao(self, tmp_path: Path, entrada: Path):
        """Blender pode sair 0 sem escrever nada; o wrapper nao pode acreditar."""

        async def fake_run(args):
            return 0, b"", b""

        otimizador = self._otimizador(tmp_path)
        with patch.object(otimizador, "_run_blender", side_effect=fake_run):
            with pytest.raises(GlbOptimizationError, match="nao foi criado"):
                await otimizador.optimize(
                    GlbOptimizationInput(
                        input_glb=entrada, output_glb=tmp_path / "f.glb"
                    )
                )

    @pytest.mark.asyncio
    async def test_entrada_ausente_vira_excecao(self, tmp_path: Path):
        otimizador = self._otimizador(tmp_path)
        with pytest.raises(GlbOptimizationError, match="entrada nao encontrado"):
            await otimizador.optimize(
                GlbOptimizationInput(
                    input_glb=tmp_path / "nao_existe.glb",
                    output_glb=tmp_path / "f.glb",
                )
            )

    @pytest.mark.asyncio
    async def test_blender_ausente_vira_excecao(self, tmp_path: Path, entrada: Path):
        otimizador = BlenderGlbOptimizer(
            blender_executable=tmp_path / "sem_blender.exe",
            script_path=SCRIPT_PATH,
        )
        with pytest.raises(GlbOptimizationError, match="Blender nao encontrado"):
            await otimizador.optimize(
                GlbOptimizationInput(input_glb=entrada, output_glb=tmp_path / "f.glb")
            )

    def test_script_existe_no_repo(self):
        """O caminho default do script e resolvido em import time; se o arquivo
        for renomeado, o erro tem que aparecer aqui e nao so em producao."""
        assert SCRIPT_PATH.exists()
