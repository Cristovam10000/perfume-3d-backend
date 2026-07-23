"""Teste de integração real contra o contêiner Hunyuan rodando.

Pulado automaticamente se o serviço não estiver respondendo em :7860.
Útil para validar manualmente após `docker compose up hunyuan`.

Para rodar:
    $env:RUN_HUNYUAN_REAL="1"
    pytest tests/integration/test_hunyuan_real.py -m slow -v

Expectativa de tempo: 2–5 minutos na RTX 5050 com mmgp profile 4.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from app.modules.captures.processor import Hunyuan3DProcessor, ProcessingInput


@pytest.fixture(scope="module")
def hunyuan_url() -> str:
    """Verifica se o serviço Hunyuan está respondendo e pronto antes dos testes."""
    habilitado = os.getenv("RUN_HUNYUAN_REAL", "").strip().lower()
    if habilitado not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "Teste real do Hunyuan desabilitado por padrao; "
            "defina RUN_HUNYUAN_REAL=1 para rodar manualmente."
        )

    url = "http://localhost:7860"
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        health = resp.json()
        if resp.status_code != 200 or health.get("status") != "ready":
            pytest.skip(f"Hunyuan não está pronto em {url}: {resp.text}")
        if health.get("shape_mode") != "multi-view" or health.get("fallback") is not False:
            pytest.fail(
                "Hunyuan respondeu ready, mas não carregou o checkpoint multi-view "
                f"principal: {health}"
            )
    except Exception as exc:
        pytest.skip(f"Hunyuan não está rodando em {url}: {exc}")
    return url


def _gerar_imagem_sintetica(path: Path, cor: tuple[int, int, int]) -> None:
    """Gera PNG RGBA sintético com cilindro colorido em fundo transparente.

    Simula a silhueta de um frasco de perfume visto de frente — geometria
    simples suficiente para validar que o pipeline completo (forma + textura)
    retorna um GLB sem erros.
    """
    from PIL import Image, ImageDraw

    # Imagem 512×768 RGBA — proporção típica de frasco alto.
    img = Image.new("RGBA", (512, 768), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Elipse central simula corpo do frasco com a cor fornecida.
    draw.ellipse([(128, 80), (384, 688)], fill=(*cor, 255))

    # Tampa retangular no topo.
    draw.rectangle([(192, 30), (320, 90)], fill=(*cor, 220))

    img.save(path, format="PNG")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_geracao_real_com_entrada_sintetica(hunyuan_url: str, tmp_path: Path):
    """Testa a geração de modelo 3D com 4 imagens sintéticas de frasco.

    Valida que o serviço retorna um GLB com header válido ('glTF') e tamanho
    plausível para um modelo com textura. Não valida qualidade visual — isso
    exigiria inspeção humana ou comparação com baseline renderizado.
    """
    # Gera 4 vistas sintéticas do frasco com cores levemente diferentes
    # para simular variação de iluminação entre ângulos.
    cores = [
        (180, 120, 60),   # frente — cor base dourada
        (160, 105, 50),   # lateral esquerda — levemente mais escura
        (170, 110, 55),   # traseira — similar à frente
        (200, 140, 75),   # lateral direita — highlight
    ]

    imagens: list[Path] = []
    for i, cor in enumerate(cores):
        caminho = tmp_path / f"frasco_{i}.png"
        _gerar_imagem_sintetica(caminho, cor)
        imagens.append(caminho)

    saida = tmp_path / "modelo_real.glb"
    processor = Hunyuan3DProcessor(
        service_url=hunyuan_url,
        timeout_seconds=1200.0,
        octree_resolution=384,
        num_inference_steps=75,
        guidance_scale=7.5,
        mc_algo="dmc",
        texture_resolution=2048,
    )

    resultado = await processor.process(
        ProcessingInput(
            job_id="test-integracao-real",
            image_paths=imagens,
            output_path=saida,
        )
    )

    assert resultado.output_path == saida
    assert saida.exists(), "Arquivo GLB não foi criado"

    bytes_glb = saida.read_bytes()
    assert bytes_glb[:4] == b"glTF", (
        f"Header inválido — esperado b'glTF', obtido {bytes_glb[:4]!r}"
    )
    # Um GLB com textura PBR deve ter pelo menos ~100KB; modelos abaixo disso
    # indicam falha silenciosa na texturização ou exportação incompleta.
    assert len(bytes_glb) > 100_000, (
        f"GLB muito pequeno ({len(bytes_glb)} bytes); provável falha na texturização"
    )
