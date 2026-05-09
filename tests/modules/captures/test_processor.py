from __future__ import annotations

import struct
from pathlib import Path

import httpx
import pytest

from app.modules.captures.processor import (
    FakeProcessor,
    Hunyuan3DProcessor,
    Processor,
    ProcessingError,
    ProcessingInput,
    _build_cube_glb,
)


# ---------------------------------------------------------- transport fake para testes


class _FakeTransport(httpx.AsyncBaseTransport):
    """Transport httpx que delega para um handler assíncrono fornecido pelo teste.

    Lê o corpo completo do request antes de chamar o handler para permitir
    inspeção do conteúdo multipart sem precisar de parser externo.
    """

    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Consome o stream para que o handler possa inspecionar o corpo.
        corpo = b"".join([chunk async for chunk in request.stream])
        return await self._handler(request, corpo)


def _assert_valid_glb(data: bytes) -> None:
    """Verifica header + layout mínimo de um binário glTF 2.0."""
    assert len(data) >= 20, "GLB muito pequeno para conter header + chunk JSON"

    magic, version, total_length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "Magic header deve ser 'glTF'"
    assert version == 2, "Apenas glTF 2.0 é suportado"
    assert total_length == len(data), "Campo length do header não bate com o tamanho real"

    # Primeiro chunk deve ser JSON.
    json_chunk_length, json_chunk_type = struct.unpack_from("<II", data, 12)
    assert json_chunk_type == 0x4E4F534A, "Primeiro chunk precisa ser JSON"
    assert json_chunk_length % 4 == 0, "Chunk JSON deve ser múltiplo de 4"


class TestBuildCubeGlb:
    def test_bytes_form_valid_glb_header(self):
        data = _build_cube_glb()
        _assert_valid_glb(data)

    def test_contains_bin_chunk_after_json(self):
        data = _build_cube_glb()
        json_len = struct.unpack_from("<I", data, 12)[0]
        bin_offset = 12 + 8 + json_len
        bin_len, bin_type = struct.unpack_from("<II", data, bin_offset)
        assert bin_type == 0x004E4942, "Segundo chunk precisa ser BIN"
        assert bin_len > 0, "Buffer binário do cubo não pode ser vazio"


class TestFakeProcessor:
    def test_is_processor_subclass(self):
        assert issubclass(FakeProcessor, Processor)

    @pytest.mark.asyncio
    async def test_writes_valid_glb_to_output_path(self, tmp_path: Path):
        output = tmp_path / "models" / "job-123.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        result = await processor.process(
            ProcessingInput(
                job_id="job-123",
                image_paths=[tmp_path / "a.jpg", tmp_path / "b.jpg"],
                output_path=output,
            )
        )

        assert result.output_path == output
        assert output.exists(), "Processor deveria ter criado o arquivo .glb"
        _assert_valid_glb(output.read_bytes())

    @pytest.mark.asyncio
    async def test_creates_parent_directory_if_missing(self, tmp_path: Path):
        output = tmp_path / "does" / "not" / "exist" / "model.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        await processor.process(
            ProcessingInput(
                job_id="job-xyz",
                image_paths=[],
                output_path=output,
            )
        )

        assert output.exists()

    @pytest.mark.asyncio
    async def test_message_mentions_image_count(self, tmp_path: Path):
        output = tmp_path / "model.glb"
        processor = FakeProcessor(simulated_duration=0.0)

        result = await processor.process(
            ProcessingInput(
                job_id="j",
                image_paths=[tmp_path / f"{i}.jpg" for i in range(7)],
                output_path=output,
            )
        )

        assert "7" in result.message


# ---------------------------------------------------------- TestHunyuan3DProcessor


class TestHunyuan3DProcessor:
    """Testa o cliente HTTP do Hunyuan3DProcessor.

    NÃO testa o serviço Hunyuan em si (isso depende de GPU e contêiner).
    Usa _FakeTransport para simular respostas do contêiner sem rede real.
    """

    def _make_fake_images(self, tmp_path: Path, n: int) -> list[Path]:
        """Cria n arquivos PNG mínimos para uso nos testes."""
        imagens = []
        for i in range(n):
            p = tmp_path / f"foto_{i}.png"
            p.write_bytes(b"fake_png_data")
            imagens.append(p)
        return imagens

    def test_is_processor_subclass(self):
        assert issubclass(Hunyuan3DProcessor, Processor)

    def test_parametros_default(self):
        proc = Hunyuan3DProcessor()
        assert proc.service_url == "http://localhost:7860"
        assert proc.timeout_seconds == 1200.0
        assert proc.octree_resolution == 384
        assert proc.num_inference_steps == 75
        assert proc.guidance_scale == 7.5
        assert proc.mc_algo == "mc"
        assert proc.texture_resolution == 2048

    @pytest.mark.asyncio
    async def test_health_check_chamado_antes_do_generate(self, tmp_path: Path):
        """Verifica que /health é consultado antes de qualquer /generate."""
        ordem_chamadas: list[str] = []

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            ordem_chamadas.append(request.url.path)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                return httpx.Response(200, content=_build_cube_glb())
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 2)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        await proc.process(
            ProcessingInput(
                job_id="test-ordem",
                image_paths=imagens,
                output_path=tmp_path / "model.glb",
            )
        )

        assert ordem_chamadas[0] == "/health", "health deve ser verificado antes de generate"
        assert "/generate" in ordem_chamadas

    @pytest.mark.asyncio
    async def test_health_loading_retenta_e_falha(self, tmp_path: Path):
        """Serviço sempre 'loading' → ProcessingError após 3 tentativas."""
        n_chamadas = 0

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            nonlocal n_chamadas
            if request.url.path == "/health":
                n_chamadas += 1
                return httpx.Response(200, json={"status": "loading"})
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 1)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        with pytest.raises(ProcessingError, match="não está pronto"):
            await proc.process(
                ProcessingInput(
                    job_id="test-loading",
                    image_paths=imagens,
                    output_path=tmp_path / "model.glb",
                )
            )

        assert n_chamadas == 3, f"Esperava 3 tentativas, fez {n_chamadas}"

    @pytest.mark.asyncio
    async def test_generate_bem_sucedido_grava_glb(self, tmp_path: Path):
        """Caminho feliz: GLB válido é gravado em output_path."""
        glb_esperado = _build_cube_glb()

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                return httpx.Response(200, content=glb_esperado)
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 3)
        saida = tmp_path / "subdir" / "modelo.glb"

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        resultado = await proc.process(
            ProcessingInput(
                job_id="test-sucesso",
                image_paths=imagens,
                output_path=saida,
            )
        )

        assert resultado.output_path == saida
        assert saida.exists()
        assert saida.read_bytes() == glb_esperado

    @pytest.mark.asyncio
    async def test_no_maximo_6_imagens_enviadas(self, tmp_path: Path):
        """Com 8 imagens de entrada, apenas 6 devem ser enviadas ao serviço."""
        n_imagens_recebidas = 0

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            nonlocal n_imagens_recebidas
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                # Cada arquivo no multipart tem um Content-Disposition com name="images".
                n_imagens_recebidas = corpo.count(b'name="images"')
                return httpx.Response(200, content=_build_cube_glb())
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 8)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        await proc.process(
            ProcessingInput(
                job_id="test-limite",
                image_paths=imagens,
                output_path=tmp_path / "model.glb",
            )
        )

        assert n_imagens_recebidas == 6, (
            f"Esperava 6 imagens no multipart, contou {n_imagens_recebidas}"
        )

    @pytest.mark.asyncio
    async def test_parametros_de_qualidade_sao_enviados(self, tmp_path: Path):
        """Verifica os campos multipart que controlam qualidade no container."""
        corpo_generate = b""

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            nonlocal corpo_generate
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                corpo_generate = corpo
                return httpx.Response(200, content=_build_cube_glb())
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 2)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        await proc.process(
            ProcessingInput(
                job_id="test-parametros-qualidade",
                image_paths=imagens,
                output_path=tmp_path / "model.glb",
            )
        )

        for nome, valor in {
            "octree_resolution": b"384",
            "num_inference_steps": b"75",
            "guidance_scale": b"7.5",
            "mc_algo": b"mc",
            "texture_resolution": b"2048",
        }.items():
            assert f'name="{nome}"'.encode() in corpo_generate
            assert valor in corpo_generate

    @pytest.mark.asyncio
    async def test_resposta_nao_200_levanta_processing_error(self, tmp_path: Path):
        """HTTP 500 do serviço deve virar ProcessingError com status no msg."""
        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                return httpx.Response(500, text="Internal Server Error: OOM")
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 1)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        with pytest.raises(ProcessingError, match="500"):
            await proc.process(
                ProcessingInput(
                    job_id="test-500",
                    image_paths=imagens,
                    output_path=tmp_path / "model.glb",
                )
            )

    @pytest.mark.asyncio
    async def test_resposta_invalida_sem_magic_glb_levanta_error(self, tmp_path: Path):
        """Resposta com bytes que não começam com 'glTF' deve levantar ProcessingError."""
        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                return httpx.Response(200, content=b"not a glb file at all")
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 1)

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        with pytest.raises(ProcessingError, match="não é um GLB válido"):
            await proc.process(
                ProcessingInput(
                    job_id="test-invalido",
                    image_paths=imagens,
                    output_path=tmp_path / "model.glb",
                )
            )

    @pytest.mark.asyncio
    async def test_template_id_e_liquid_color_sao_ignorados(self, tmp_path: Path):
        """template_id e liquid_color no ProcessingInput não causam erro nem alteram o GLB."""
        glb_esperado = _build_cube_glb()

        async def fake_handler(request: httpx.Request, corpo: bytes) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ready"})
            if request.url.path == "/generate":
                return httpx.Response(200, content=glb_esperado)
            return httpx.Response(404)

        transport = _FakeTransport(fake_handler)
        imagens = self._make_fake_images(tmp_path, 2)
        saida = tmp_path / "model.glb"

        proc = Hunyuan3DProcessor(_transport=transport, _retry_interval=0)
        resultado = await proc.process(
            ProcessingInput(
                job_id="test-campos-ignorados",
                image_paths=imagens,
                output_path=saida,
                template_id="rectangular_basic",
                liquid_color="#FF00AA",
                label_image=tmp_path / "label.png",
            )
        )

        # Campos extras não devem impedir a geração bem-sucedida do modelo.
        assert resultado.output_path == saida
        assert saida.read_bytes() == glb_esperado
