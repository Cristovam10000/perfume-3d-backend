"""Testes unitarios da configuracao do servidor Hunyuan em Docker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def hunyuan_server():
    caminho = Path(__file__).parents[1] / "docker" / "hunyuan" / "server.py"
    spec = importlib.util.spec_from_file_location("hunyuan_docker_server_test", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _limpar_env_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    nomes = (
        "HUNYUAN_TEXTURE_REPO",
        "HUNYUAN_SHAPE_REPO",
        "HUNYUAN_SHAPE_SUBFOLDER",
        "HUNYUAN_SHAPE_VARIANT",
        "HUNYUAN_ALLOW_SINGLE_VIEW_FALLBACK",
        "HUNYUAN_FALLBACK_SHAPE_REPO",
        "HUNYUAN_FALLBACK_SHAPE_SUBFOLDER",
        "HUNYUAN_FALLBACK_SHAPE_VARIANT",
    )
    for nome in nomes:
        monkeypatch.delenv(nome, raising=False)


def test_checkpoints_padrao_separam_multiview_e_fallback(
    hunyuan_server, monkeypatch: pytest.MonkeyPatch
):
    _limpar_env_checkpoints(monkeypatch)

    candidatos = hunyuan_server._candidatos_shape()

    assert candidatos == [
        hunyuan_server.ShapeCheckpoint(
            repo="tencent/Hunyuan3D-2mv",
            subfolder="hunyuan3d-dit-v2-mv",
            variant="fp16",
            fallback=False,
        ),
        hunyuan_server.ShapeCheckpoint(
            repo="tencent/Hunyuan3D-2",
            subfolder="hunyuan3d-dit-v2-0",
            variant="fp16",
            fallback=True,
        ),
    ]


def test_variante_fp16_e_tentada_antes_do_single_view(
    hunyuan_server, monkeypatch: pytest.MonkeyPatch
):
    _limpar_env_checkpoints(monkeypatch)
    monkeypatch.setenv("HUNYUAN_SHAPE_VARIANT", "bf16")

    candidatos = hunyuan_server._candidatos_shape()

    assert [(item.repo, item.subfolder, item.variant) for item in candidatos] == [
        ("tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv", "bf16"),
        ("tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv", "fp16"),
        ("tencent/Hunyuan3D-2", "hunyuan3d-dit-v2-0", "fp16"),
    ]


def test_download_shape_limita_arquivos_ao_safetensors(hunyuan_server):
    checkpoint = hunyuan_server.ShapeCheckpoint(
        repo="tencent/Hunyuan3D-2mv",
        subfolder="hunyuan3d-dit-v2-mv",
        variant="fp16",
    )

    assert hunyuan_server._arquivos_checkpoint_shape(checkpoint) == [
        "hunyuan3d-dit-v2-mv/config.yaml",
        "hunyuan3d-dit-v2-mv/model.fp16.safetensors",
    ]


@pytest.mark.asyncio
async def test_health_informa_checkpoint_multiview(
    hunyuan_server, monkeypatch: pytest.MonkeyPatch
):
    class MVImageProcessorV2:
        pass

    class Pipeline:
        image_processor = MVImageProcessorV2()

    checkpoint = hunyuan_server.ShapeCheckpoint(
        repo="tencent/Hunyuan3D-2mv",
        subfolder="hunyuan3d-dit-v2-mv",
        variant="fp16",
    )
    monkeypatch.setattr(hunyuan_server, "_pipeline_forma", Pipeline())
    monkeypatch.setattr(hunyuan_server, "_modelo_carregado", True)
    monkeypatch.setattr(hunyuan_server, "_erro_carga", None)
    monkeypatch.setattr(hunyuan_server, "_shape_carregado", checkpoint)

    resposta = await hunyuan_server.health()

    assert resposta == {
        "status": "ready",
        "shape_mode": "multi-view",
        "shape_repo": "tencent/Hunyuan3D-2mv",
        "shape_subfolder": "hunyuan3d-dit-v2-mv",
        "shape_variant": "fp16",
        "fallback": False,
    }


def test_single_view_usa_apenas_primeira_imagem(hunyuan_server, monkeypatch):
    class SingleImageProcessor:
        pass

    class Pipeline:
        image_processor = SingleImageProcessor()

    monkeypatch.setattr(hunyuan_server, "_pipeline_forma", Pipeline())
    imagens = [object(), object(), object(), object()]

    assert hunyuan_server._montar_entrada_forma(imagens) is imagens[0]
