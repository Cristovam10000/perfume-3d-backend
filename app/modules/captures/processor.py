from __future__ import annotations

import asyncio
import json
import struct
from abc import ABC, abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import httpx

from ...core.logging import get_logger

_log = get_logger("captures.hunyuan_processor")


class ProcessingError(Exception):
    """Falha na execução do pipeline 3D pelo processor.

    Levantada pelos processors quando algo no pipeline falha de forma não-recuperável
    (binário ausente, subprocess crashou, output não foi gerado, etc).
    Capturada pelo service, que marca o job como `error`.
    """


@dataclass(frozen=True)
class ProcessingInput:
    job_id: str
    image_paths: list[Path]
    output_path: Path
    # Opcionais — usados por processors que precisam (TemplateProcessor / pipeline).
    # FakeProcessor ignora.
    template_id: str | None = None
    liquid_color: str | None = None
    label_image: Path | None = None
    # product_id veio do POST /captures (form-data). Quando presente, o
    # IntegratedPipeline amarra o GLB ao produto comercial via modelos_3d_produto
    # ao final do stage de cache. Quando None, o cache popula apenas a
    # modelos_3d_universais sem vinculo de tenant.
    product_id: int | None = None
    # Rótulos de vista enviados pelo app guiado, paralelos a image_paths.
    # Cada item é None (sem rótulo) ou um dos valores de CARDINAL_VIEWS / "extra".
    # O IntegratedPipeline usa esses rótulos via LabeledViewRouter; quando todos
    # são None, recorre ao CLIPViewRouter.
    views: list[str | None] | None = None
    # Material do frasco declarado pelo usuário ("glass" | "opaque"). Quando
    # presente, decide o body_mode do refiner sem consultar o CLIP. None = não
    # informado, o pipeline classifica.
    material: str | None = None


@dataclass(frozen=True)
class ProcessingResult:
    output_path: Path
    message: str
    # Diagnostico para o service repassar ao status do job.
    origem: str = "generated"  # "generated" | "cache" | "template-fallback" | "fake"
    similarity: float | None = None  # preenchido em cache hits


class Processor(ABC):
    """Contrato abstrato do pipeline de reconstrução 3D.

    Qualquer backend (fake, template, Meshroom/AliceVision, etc.) deve implementar
    este método. O service só conhece esta interface — trocar a implementação real
    não exige mudar nada fora deste módulo.
    """

    @abstractmethod
    async def process(self, input: ProcessingInput) -> ProcessingResult: ...


class FakeProcessor(Processor):
    """Gera um `.glb` sintético (cubo) para destravar o fluxo do front.

    Na fase real, esta classe é substituída por um wrapper do Meshroom. O
    `simulated_duration` existe para que o app veja transições de status
    (`waiting → processing → completed`) em um tempo plausível.
    """

    def __init__(self, simulated_duration: float = 3.0):
        self.simulated_duration = simulated_duration

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        if self.simulated_duration > 0:
            await asyncio.sleep(self.simulated_duration)

        glb_bytes = _build_cube_glb()
        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(glb_bytes)

        return ProcessingResult(
            output_path=input.output_path,
            message=f"Modelo gerado a partir de {len(input.image_paths)} imagens",
        )


# --- GLB binário mínimo (stdlib pura) -------------------------------------
# Especificação: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#glb-file-format-specification
# Header  : magic "glTF" + versão 2 + length total
# Chunk 0 : JSON (estrutura da cena)
# Chunk 1 : BIN (buffer com posições e índices)

_GLB_MAGIC = 0x46546C67          # "glTF"
_CHUNK_JSON = 0x4E4F534A         # "JSON"
_CHUNK_BIN = 0x004E4942          # "BIN\0"
_COMP_TYPE_UNSIGNED_SHORT = 5123
_COMP_TYPE_FLOAT = 5126
_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963
_MODE_TRIANGLES = 4


def _build_cube_glb() -> bytes:
    """Constrói um .glb contendo um único cubo centrado na origem."""
    vertices = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    # Dois triângulos por face, 12 triângulos no total.
    indices = [
        0, 2, 1, 0, 3, 2,
        4, 5, 6, 4, 6, 7,
        0, 4, 7, 0, 7, 3,
        1, 2, 6, 1, 6, 5,
        3, 7, 6, 3, 6, 2,
        0, 1, 5, 0, 5, 4,
    ]

    vertex_bytes = b"".join(struct.pack("<fff", *v) for v in vertices)
    index_bytes = b"".join(struct.pack("<H", i) for i in indices)
    bin_data = vertex_bytes + index_bytes
    bin_data += b"\x00" * ((4 - len(bin_data) % 4) % 4)

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    gltf = {
        "asset": {"version": "2.0", "generator": "perfume-3d-mvp fake processor"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": _MODE_TRIANGLES,
                    }
                ]
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": _COMP_TYPE_FLOAT,
                "count": len(vertices),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            },
            {
                "bufferView": 1,
                "componentType": _COMP_TYPE_UNSIGNED_SHORT,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(vertex_bytes),
                "target": _TARGET_ARRAY_BUFFER,
            },
            {
                "buffer": 0,
                "byteOffset": len(vertex_bytes),
                "byteLength": len(index_bytes),
                "target": _TARGET_ELEMENT_ARRAY_BUFFER,
            },
        ],
        "buffers": [{"byteLength": len(bin_data)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # glTF exige que o chunk JSON seja múltiplo de 4; preenche com espaços.
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)

    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    header = struct.pack("<III", _GLB_MAGIC, 2, total_length)
    json_chunk = struct.pack("<II", len(json_bytes), _CHUNK_JSON) + json_bytes
    bin_chunk = struct.pack("<II", len(bin_data), _CHUNK_BIN) + bin_data

    return header + json_chunk + bin_chunk


# --------------------------------------------------------------------------
# Hunyuan3DProcessor: cliente HTTP para o serviço de IA rodando em Docker.


class Hunyuan3DProcessor(Processor):
    """Cliente HTTP para o serviço Hunyuan3D-2mv rodando em contêiner Docker.

    Não importa torch, transformers, nem qualquer dependência ML — toda a
    inferência acontece no contêiner separado (ver docker/hunyuan/). Este
    processor só monta a requisição multipart, aguarda o GLB e o grava em disco.

    Pré-requisitos antes de instanciar em produção:
    - Contêiner `perfume-hunyuan` rodando e com modelo carregado (/health → ready).
    - Imagens DEVEM estar pré-segmentadas pelo BackgroundRemover (Fase 1);
      fundo removido melhora significativamente a qualidade do mesh gerado.

    `template_id`, `liquid_color` e `label_image` do `ProcessingInput` são
    **ignorados**: o Hunyuan infere geometria e textura diretamente das fotos,
    sem necessitar de template ou cor explícita. A integração com esses campos
    será avaliada na Fase 4 (roteamento entre processors).
    """

    _MAX_IMAGENS = 6  # Hunyuan3D-2mv foi treinado com no máximo 6 vistas simultâneas

    def __init__(
        self,
        service_url: str = "http://localhost:7860",
        timeout_seconds: float = 1200.0,  # IA e lenta; 20 min para steps/textura altos
        octree_resolution: int = 384,     # qualidade maior, exige mais VRAM
        num_inference_steps: int = 75,
        guidance_scale: float = 7.5,
        mc_algo: str = "mc",
        texture_resolution: int = 2048,
        _transport=None,          # parâmetro privado, apenas para testes unitários
        _retry_interval: float = 5.0,     # intervalo entre retentativas de health check
    ):
        self.service_url = service_url
        self.timeout_seconds = timeout_seconds
        self.octree_resolution = octree_resolution
        self.num_inference_steps = num_inference_steps
        self.guidance_scale = guidance_scale
        self.mc_algo = mc_algo
        self.texture_resolution = texture_resolution
        self._transport = _transport
        self._retry_interval = _retry_interval

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        timeout = httpx.Timeout(self.timeout_seconds)
        kwargs: dict = {"base_url": self.service_url, "timeout": timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport

        async with httpx.AsyncClient(**kwargs) as cliente:
            await self._aguardar_servico(cliente)
            bytes_glb = await self._gerar_modelo(cliente, input)

        input.output_path.parent.mkdir(parents=True, exist_ok=True)
        input.output_path.write_bytes(bytes_glb)

        n_enviadas = min(len(input.image_paths), self._MAX_IMAGENS)
        return ProcessingResult(
            output_path=input.output_path,
            message=f"Modelo gerado via Hunyuan3D-2mv a partir de {n_enviadas} imagem(ns)",
        )

    # ------------------------------------------------------------------ internos

    async def _aguardar_servico(self, cliente: httpx.AsyncClient) -> None:
        """Verifica readiness com até 3 tentativas antes de desistir.

        Necessário porque o modelo leva ~30s para carregar após o container subir.
        """
        tentativas = 3
        for tentativa in range(1, tentativas + 1):
            try:
                resp = await cliente.get("/health")
                if resp.json().get("status") == "ready":
                    return
                _log.info(
                    "Hunyuan ainda carregando (tentativa %d/%d): %s",
                    tentativa, tentativas, resp.json(),
                )
            except Exception as exc:
                _log.warning(
                    "Falha ao contatar Hunyuan (tentativa %d/%d): %s",
                    tentativa, tentativas, exc,
                )

            if tentativa < tentativas:
                await asyncio.sleep(self._retry_interval)

        raise ProcessingError(
            f"Hunyuan service não está pronto em {self.service_url}"
        )

    async def _gerar_modelo(
        self, cliente: httpx.AsyncClient, input: ProcessingInput
    ) -> bytes:
        """Envia as imagens (máx. 6) e baixa o GLB resultante."""
        imagens = input.image_paths[: self._MAX_IMAGENS]

        # ExitStack garante fechamento dos handles mesmo em caso de exceção.
        with ExitStack() as pilha:
            arquivos = []
            for caminho in imagens:
                handle = pilha.enter_context(open(caminho, "rb"))
                arquivos.append(("images", (caminho.name, handle, "image/png")))

            dados_form = {
                "octree_resolution": str(self.octree_resolution),
                "num_inference_steps": str(self.num_inference_steps),
                "guidance_scale": str(self.guidance_scale),
                "mc_algo": self.mc_algo,
                "texture_resolution": str(self.texture_resolution),
            }

            _log.info(
                "Enviando %d imagem(ns) ao Hunyuan (%s)...",
                len(arquivos), self.service_url,
            )
            resp = await cliente.post("/generate", files=arquivos, data=dados_form)

        if resp.status_code != 200:
            trecho = resp.text[:500]
            raise ProcessingError(
                f"Hunyuan retornou HTTP {resp.status_code}: {trecho}"
            )

        bytes_glb = resp.content
        if not bytes_glb.startswith(b"glTF"):
            raise ProcessingError("Resposta do Hunyuan não é um GLB válido")

        _log.info("GLB recebido com sucesso: %d bytes", len(bytes_glb))
        return bytes_glb
