"""Testes do ViewTextureProjector (projeção de foto real em faces do GLB).

O Blender real não roda aqui — `_run_blender` é substituído por um fake, então
o que se valida é o contrato do wrapper: argumentos montados, eixo repassado,
validações de pré-condição e tradução de falha em exceção.

O comportamento geométrico (quais faces, qual UV) é do script Blender e foi
verificado rodando o script de verdade sobre os GLBs dos jobs reais.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.view_texture_projector import (
    AXIS_BACK,
    AXIS_FRONT,
    AXIS_TOP,
    BlenderViewTextureProjector,
    DisabledViewTextureProjector,
    ViewTextureProjectionError,
    ViewTextureProjectionInput,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT
    / "app"
    / "modules"
    / "captures"
    / "blender_scripts"
    / "project_view_texture.py"
)


def _minimal_glb() -> bytes:
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


@pytest.fixture
def cenario(tmp_path: Path):
    """GLB de entrada, foto e um executável falso do Blender."""
    entrada = tmp_path / "refined.glb"
    entrada.write_bytes(_minimal_glb())
    foto = tmp_path / "back.png"
    foto.write_bytes(b"\x89PNG\r\n\x1a\n-stub")
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"stub")
    return entrada, foto, blender


def _fake_runner(*, returncode: int = 0, criar_saida: bool = True):
    """Substitui a chamada ao Blender e registra os argumentos recebidos."""
    capturados: list[list[str]] = []

    def runner(self, args):
        capturados.append(list(args))
        if criar_saida and returncode == 0:
            saida = Path(args[args.index("--output") + 1])
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_bytes(_minimal_glb())
        return returncode, b"", b"boom" if returncode else b""

    return runner, capturados


# ------------------------------------------------------------- disabled


@pytest.mark.asyncio
async def test_disabled_copia_sem_alterar(cenario, tmp_path: Path):
    entrada, foto, _ = cenario
    saida = tmp_path / "out.glb"

    resultado = await DisabledViewTextureProjector().project(
        ViewTextureProjectionInput(
            input_glb=entrada, photo=foto, output_glb=saida, axis=AXIS_TOP
        )
    )

    assert resultado.output_glb == saida
    assert saida.read_bytes() == entrada.read_bytes()


# -------------------------------------------------------------- blender


@pytest.mark.asyncio
async def test_monta_argumentos_do_eixo_topo(cenario, tmp_path: Path):
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_top.glb",
                axis=AXIS_TOP,
                cosine_threshold=0.45,
            )
        )

    args = capturados[0]
    assert args[0] == str(blender)
    assert "--background" in args
    assert args[args.index("--axis") + 1] == AXIS_TOP
    assert args[args.index("--photo") + 1] == str(foto)
    assert args[args.index("--cosine-threshold") + 1] == "0.45"


@pytest.mark.asyncio
async def test_monta_argumentos_do_eixo_costas(cenario, tmp_path: Path):
    """Mesmo wrapper, eixo diferente — é o que permite uma instância só."""
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_back.glb",
                axis=AXIS_BACK,
            )
        )

    assert capturados[0][capturados[0].index("--axis") + 1] == AXIS_BACK


@pytest.mark.asyncio
async def test_eixo_invalido_falha_antes_de_chamar_o_blender(cenario, tmp_path: Path):
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        with pytest.raises(ViewTextureProjectionError, match="Eixo inválido"):
            await BlenderViewTextureProjector(blender_executable=blender).project(
                ViewTextureProjectionInput(
                    input_glb=entrada,
                    photo=foto,
                    output_glb=tmp_path / "x.glb",
                    axis="x_pos",
                )
            )

    assert capturados == [], "não deveria ter chamado o Blender"


@pytest.mark.asyncio
async def test_exit_code_diferente_de_zero_vira_erro(cenario, tmp_path: Path):
    entrada, foto, blender = cenario
    runner, _ = _fake_runner(returncode=1, criar_saida=False)

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        with pytest.raises(ViewTextureProjectionError, match="retornou 1"):
            await BlenderViewTextureProjector(blender_executable=blender).project(
                ViewTextureProjectionInput(
                    input_glb=entrada,
                    photo=foto,
                    output_glb=tmp_path / "x.glb",
                    axis=AXIS_BACK,
                )
            )


@pytest.mark.asyncio
async def test_saida_ausente_vira_erro(cenario, tmp_path: Path):
    """Blender pode sair com 0 sem escrever nada; o wrapper não pode confiar."""
    entrada, foto, blender = cenario
    runner, _ = _fake_runner(criar_saida=False)

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        with pytest.raises(ViewTextureProjectionError, match="nao foi criado"):
            await BlenderViewTextureProjector(blender_executable=blender).project(
                ViewTextureProjectionInput(
                    input_glb=entrada,
                    photo=foto,
                    output_glb=tmp_path / "x.glb",
                    axis=AXIS_TOP,
                )
            )


@pytest.mark.asyncio
async def test_foto_ausente_falha_com_mensagem_clara(cenario, tmp_path: Path):
    entrada, _, blender = cenario

    with pytest.raises(ViewTextureProjectionError, match="Imagem nao encontrada"):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=tmp_path / "nao_existe.png",
                output_glb=tmp_path / "x.glb",
                axis=AXIS_BACK,
            )
        )


@pytest.mark.asyncio
async def test_blender_ausente_falha_com_mensagem_clara(cenario, tmp_path: Path):
    entrada, foto, _ = cenario

    with pytest.raises(ViewTextureProjectionError, match="Executavel do Blender"):
        await BlenderViewTextureProjector(
            blender_executable=tmp_path / "sem_blender.exe"
        ).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "x.glb",
                axis=AXIS_TOP,
            )
        )


def test_script_default_existe_no_repo():
    """O caminho default precisa apontar para o script renomeado."""
    assert SCRIPT_PATH.exists(), f"script não encontrado: {SCRIPT_PATH}"
    assert BlenderViewTextureProjector().script_path == SCRIPT_PATH


@pytest.mark.asyncio
async def test_monta_argumentos_do_eixo_frontal_com_janela(cenario, tmp_path: Path):
    """A label usa o mesmo projetor, no eixo -Y e sempre com janela.

    A janela é o que diferencia a label de topo e costas: aqueles cobrem o alvo
    inteiro, a label ocupa um retângulo da frente. Sem ela a imagem esticaria
    sobre o frasco todo.
    """
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_label.glb",
                axis=AXIS_FRONT,
                window=(0.25, 0.4, 0.75, 0.55),
            )
        )

    args = capturados[0]
    assert args[args.index("--axis") + 1] == AXIS_FRONT
    assert args[args.index("--window") + 1] == "0.250000,0.400000,0.750000,0.550000"


@pytest.mark.asyncio
async def test_sem_janela_nao_passa_o_argumento(cenario, tmp_path: Path):
    """Topo e costas seguem idênticos — a janela é opcional por construção."""
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_top.glb",
                axis=AXIS_TOP,
            )
        )

    assert "--window" not in capturados[0]


@pytest.mark.asyncio
async def test_bake_passa_assar_para_o_script(cenario, tmp_path: Path):
    """A label precisa assar: glTF so admite um material PBR por primitiva.

    Sem `--assar` o script cria material separado, e o exportador descarta o
    decal em silencio — medido no job 3a3adbc8, o GLB saia com uma imagem so.
    """
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_label.glb",
                axis=AXIS_FRONT,
                window=(0.25, 0.4, 0.75, 0.55),
                bake=True,
            )
        )

    assert "--assar" in capturados[0]


@pytest.mark.asyncio
async def test_sem_bake_nao_passa_assar(cenario, tmp_path: Path):
    """Topo e costas substituem o material de proposito e nao devem assar."""
    entrada, foto, blender = cenario
    runner, capturados = _fake_runner()

    with patch.object(BlenderViewTextureProjector, "_run_blender_sync", runner):
        await BlenderViewTextureProjector(blender_executable=blender).project(
            ViewTextureProjectionInput(
                input_glb=entrada,
                photo=foto,
                output_glb=tmp_path / "with_top.glb",
                axis=AXIS_TOP,
            )
        )

    assert "--assar" not in capturados[0]
