from __future__ import annotations

import asyncio
import json
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessingInput:
    job_id: str
    image_paths: list[Path]
    output_path: Path


@dataclass(frozen=True)
class ProcessingResult:
    output_path: Path
    message: str


class Processor(ABC):
    """Contrato abstrato do pipeline de reconstrução 3D.

    Qualquer backend (fake, Meshroom/AliceVision, etc.) deve implementar este
    método. O service só conhece esta interface — trocar a implementação real
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
