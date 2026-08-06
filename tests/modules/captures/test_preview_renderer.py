"""Testes do PreviewRenderer (PNG de vitrine mostrado no card do produto).

O Blender real nao roda aqui; o que se valida e o contrato do wrapper. O
enquadramento e a iluminacao sao do script Blender e foram verificados rodando
o script de verdade sobre o GLB do job `15ef21e9`.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.preview_renderer import (
    BlenderPreviewRenderer,
    DisabledPreviewRenderer,
    PreviewRenderError,
    PreviewRenderInput,
)

BACK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    BACK_ROOT / "app" / "modules" / "captures" / "blender_scripts" / "render_preview.py"
)


def _minimal_glb() -> bytes:
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    return struct.pack("<III", 0x46546C67, 2, total) + json_chunk + bin_chunk


@pytest.fixture
def glb(tmp_path: Path) -> Path:
    caminho = tmp_path / "final.glb"
    caminho.write_bytes(_minimal_glb())
    return caminho


class TestDisabledPreviewRenderer:
    @pytest.mark.asyncio
    async def test_sinaliza_ausencia_com_excecao(self, tmp_path: Path, glb: Path):
        """Diferente dos outros Disabled*, nao ha arquivo de entrada para copiar.

        A excecao e o canal: o pipeline ja a trata como degradacao e o card
        volta ao visual generico.
        """
        with pytest.raises(PreviewRenderError, match="desabilitada"):
            await DisabledPreviewRenderer().render(
                PreviewRenderInput(input_glb=glb, output_png=tmp_path / "p.png")
            )


class TestBlenderPreviewRenderer:
    def _renderer(self, tmp_path: Path) -> BlenderPreviewRenderer:
        blender = tmp_path / "blender.exe"
        blender.write_bytes(b"fake")
        return BlenderPreviewRenderer(
            blender_executable=blender, script_path=SCRIPT_PATH
        )

    @pytest.mark.asyncio
    async def test_monta_argumentos_com_resolucao(self, tmp_path: Path, glb: Path):
        saida = tmp_path / "preview.png"
        capturados: list[str] = []

        async def fake_run(args):
            capturados.extend(args)
            saida.write_bytes(b"\x89PNG")
            return 0, b"", b""

        renderer = self._renderer(tmp_path)
        with patch.object(renderer, "_run_blender", side_effect=fake_run):
            resultado = await renderer.render(
                PreviewRenderInput(input_glb=glb, output_png=saida, resolution=256)
            )

        assert str(SCRIPT_PATH) in capturados
        assert capturados[capturados.index("--resolution") + 1] == "256"
        assert resultado.output_png == saida

    @pytest.mark.asyncio
    async def test_retorno_diferente_de_zero_vira_excecao(
        self, tmp_path: Path, glb: Path
    ):
        async def fake_run(args):
            return 1, b"", b"sem GPU"

        renderer = self._renderer(tmp_path)
        with patch.object(renderer, "_run_blender", side_effect=fake_run):
            with pytest.raises(PreviewRenderError, match="retornou 1"):
                await renderer.render(
                    PreviewRenderInput(input_glb=glb, output_png=tmp_path / "p.png")
                )

    @pytest.mark.asyncio
    async def test_png_ausente_vira_excecao(self, tmp_path: Path, glb: Path):
        async def fake_run(args):
            return 0, b"", b""

        renderer = self._renderer(tmp_path)
        with patch.object(renderer, "_run_blender", side_effect=fake_run):
            with pytest.raises(PreviewRenderError, match="nao foi criado"):
                await renderer.render(
                    PreviewRenderInput(input_glb=glb, output_png=tmp_path / "p.png")
                )

    @pytest.mark.asyncio
    async def test_glb_ausente_vira_excecao(self, tmp_path: Path):
        renderer = self._renderer(tmp_path)
        with pytest.raises(PreviewRenderError, match="entrada nao encontrado"):
            await renderer.render(
                PreviewRenderInput(
                    input_glb=tmp_path / "nao_existe.glb",
                    output_png=tmp_path / "p.png",
                )
            )

    def test_script_existe_no_repo(self):
        assert SCRIPT_PATH.exists()
