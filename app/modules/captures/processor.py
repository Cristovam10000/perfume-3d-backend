from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .template_fitting import TemplateFitAnalyzer, TemplateFittingError


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
    # Opcionais — usados por processors que precisam (TemplateProcessor).
    # FakeProcessor ignora.
    template_id: str | None = None
    liquid_color: str | None = None
    label_image: Path | None = None


@dataclass(frozen=True)
class ProcessingResult:
    output_path: Path
    message: str


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
# TemplateProcessor: invoca Blender headless para customizar um template GLB.

# Caminho default do script de customização (irmão do diretório deste módulo).
_DEFAULT_SCRIPT_PATH = Path(__file__).resolve().parent / "blender_scripts" / "customize_template.py"
_DEFAULT_FIT_SCRIPT_PATH = Path(__file__).resolve().parent / "blender_scripts" / "fit_template.py"


class TemplateProcessor(Processor):
    """Customiza um template GLB normalizado via Blender headless.

    Chama o script `app/modules/captures/blender_scripts/customize_template.py`
    como subprocess, passando template + label + cor do líquido. O script faz
    o trabalho pesado e exporta o GLB final em `input.output_path`.

    Não conhece classificação de forma — recebe `template_id` via
    `ProcessingInput`. Quando vier `None`, usa `default_template_id` (definido
    no construtor). A Etapa 14 (CLIP) preencherá o `template_id` no service.
    """

    def __init__(
        self,
        blender_executable: Path,
        templates_dir: Path,
        *,
        script_path: Path | None = None,
        default_template_id: str = "rectangular_basic",
        timeout_seconds: float = 180.0,
    ):
        self.blender_executable = Path(blender_executable)
        self.templates_dir = Path(templates_dir)
        self.script_path = Path(script_path) if script_path else _DEFAULT_SCRIPT_PATH
        self.default_template_id = default_template_id
        self.timeout_seconds = timeout_seconds

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self._assert_runtime_assets()

        template_id = input.template_id or self.default_template_id
        template_path = self.templates_dir / f"{template_id}.glb"
        if not template_path.exists():
            raise ProcessingError(
                f"Template '{template_id}' não existe em {template_path}"
            )

        # Label só é aplicada quando o caller fornece uma imagem já extraída.
        # Colar a foto inteira do produto no plano de label gera artefatos ruins.
        label_image = input.label_image
        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--template", str(template_path),
            "--output", str(input.output_path),
        ]
        if label_image is not None and label_image.exists():
            args.extend(["--label-image", str(label_image)])
        if input.liquid_color is not None:
            args.extend(["--liquid-color", input.liquid_color])

        returncode, stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise ProcessingError(
                f"Blender retornou {returncode} ao customizar template "
                f"'{template_id}': {tail}"
            )

        if not input.output_path.exists():
            raise ProcessingError(
                "Blender concluiu sem erros mas o GLB de saída não foi criado: "
                f"{input.output_path}"
            )

        return ProcessingResult(
            output_path=input.output_path,
            message=f"Modelo gerado a partir do template '{template_id}'",
        )

    def _assert_runtime_assets(self) -> None:
        if not self.blender_executable.exists():
            raise ProcessingError(
                f"Executável do Blender não encontrado: {self.blender_executable}"
            )
        if not self.script_path.exists():
            raise ProcessingError(
                f"Script do Blender não encontrado: {self.script_path}"
            )
        if not self.templates_dir.exists():
            raise ProcessingError(
                f"Diretório de templates não existe: {self.templates_dir}"
            )

    async def _run_blender(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Roda o subprocess Blender de forma assíncrona.

        Isolado em método pra permitir override em testes (evita custo de
        invocar o Blender real em cada caso). Retorna (returncode, stdout, stderr).
        """
        return await asyncio.to_thread(self._run_blender_sync, args)

    def _run_blender_sync(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Executa o Blender em uma thread.

        No Windows, alguns event loops não implementam subprocess assíncrono
        nativo. `subprocess.run` dentro de `asyncio.to_thread` mantém o servidor
        responsivo e evita `NotImplementedError` em runtime.
        """
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ProcessingError(
                f"Blender excedeu timeout de {self.timeout_seconds}s"
            ) from None

        return (
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )


class TemplateFittingProcessor(TemplateProcessor):
    """Customiza e deforma um template GLB a partir da silhueta das fotos.

    Este processor evolui o `TemplateProcessor` sem remover o caminho antigo.
    Antes de chamar o Blender, ele:

    1. segmenta a foto frontal por heuristica de fundo;
    2. estima proporcoes da silhueta;
    3. escolhe o template quando o classificador externo nao foi usado;
    4. gera recortes candidatos para label/topo;
    5. passa escalas de deformacao para `fit_template.py`.

    Dependencias de visao (Pillow/Numpy/OpenCV) continuam opcionais e sao
    carregadas apenas quando `PROCESSOR_TYPE=template_fitting`.
    """

    def __init__(
        self,
        blender_executable: Path,
        templates_dir: Path,
        *,
        script_path: Path | None = None,
        default_template_id: str = "rectangular_basic",
        timeout_seconds: float = 240.0,
        analyzer: TemplateFitAnalyzer | None = None,
        prefer_input_template_id: bool = False,
    ):
        super().__init__(
            blender_executable=blender_executable,
            templates_dir=templates_dir,
            script_path=script_path or _DEFAULT_FIT_SCRIPT_PATH,
            default_template_id=default_template_id,
            timeout_seconds=timeout_seconds,
        )
        self.analyzer = analyzer or TemplateFitAnalyzer(
            default_template_id=default_template_id
        )
        self.prefer_input_template_id = prefer_input_template_id

    async def process(self, input: ProcessingInput) -> ProcessingResult:
        self._assert_runtime_assets()

        available_template_ids = {
            path.stem
            for path in self.templates_dir.glob("*.glb")
            if path.is_file()
        }
        if not available_template_ids:
            raise ProcessingError(
                f"Nenhum template GLB encontrado em {self.templates_dir}"
            )

        work_dir = input.output_path.parent / f"{input.job_id}_fit"
        try:
            plan = await self.analyzer.analyze(
                input.image_paths,
                work_dir,
                available_template_ids=available_template_ids,
                template_hint=(
                    input.template_id if self.prefer_input_template_id else None
                ),
                explicit_label_image=input.label_image,
            )
        except TemplateFittingError as exc:
            raise ProcessingError(str(exc)) from exc

        template_id = plan.template_id or input.template_id or self.default_template_id
        template_path = self.templates_dir / f"{template_id}.glb"
        if not template_path.exists():
            raise ProcessingError(
                f"Template '{template_id}' nao existe em {template_path}"
            )

        plan.write_json(work_dir / "fit_plan.json")

        args = [
            str(self.blender_executable),
            "--background",
            "--python", str(self.script_path),
            "--",
            "--template", str(template_path),
            "--output", str(input.output_path),
            "--fit-plan", str(work_dir / "fit_plan.json"),
            "--body-width-scale", f"{plan.body_width_scale:.6f}",
            "--body-depth-scale", f"{plan.body_depth_scale:.6f}",
            "--height-scale", f"{plan.height_scale:.6f}",
            "--cap-width-scale", f"{plan.cap_width_scale:.6f}",
            "--cap-height-ratio", f"{plan.cap_height_ratio:.6f}",
        ]
        if plan.label_image is not None and plan.label_image.exists():
            args.extend(["--label-image", str(plan.label_image)])
        if plan.top_image is not None and plan.top_image.exists():
            args.extend(["--top-image", str(plan.top_image)])
        if input.liquid_color is not None:
            args.extend(["--liquid-color", input.liquid_color])

        returncode, _stdout, stderr = await self._run_blender(args)

        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace")[-500:]
            raise ProcessingError(
                f"Blender retornou {returncode} ao ajustar template "
                f"'{template_id}': {tail}"
            )

        if not input.output_path.exists():
            raise ProcessingError(
                "Blender concluiu sem erros mas o GLB ajustado nao foi criado: "
                f"{input.output_path}"
            )

        return ProcessingResult(
            output_path=input.output_path,
            message=(
                f"Modelo ajustado pelo template '{template_id}' "
                f"(silhueta {plan.metrics.aspect_ratio:.2f}, "
                f"confianca {plan.metrics.confidence:.0%})"
            ),
        )
