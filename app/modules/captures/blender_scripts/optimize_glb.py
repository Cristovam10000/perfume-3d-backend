"""Comprime o GLB final com Draco antes de entregar ao app.

Motivo: o GLB que sai do pipeline chegou a 77 MB, e o celular baixa isso por
Wi-Fi toda vez que abre o produto. A malha responde por ~90% do arquivo.

O que a medicao mostrou no job `15ef21e9` (Camille, 05/08):

    original .................... 77,08 MB
    reexportado sem mudanca ..... 77,08 MB   (a ida e volta pelo Blender e neutra)
    sem normais ................. 58,07 MB
    Draco ....................... 13,92 MB   <- 5,5x
    Draco + sem normais ......... 12,99 MB

Duas otimizacoes foram testadas e **descartadas**, ambas por medicao:

- **Remover as normais.** Economiza 0,9 MB depois do Draco, mas a malha nao e
  toda plana (510.207 de 530.544 poligonos sao flat; ~20 mil sao suavizados).
  Sem o atributo, o visualizador calcula normais planas e o sombreamento desses
  20 mil muda. Nao vale 0,9 MB.

- **Limitar o segundo UV as faces que o usam.** A camada `TEXCOORD_1` da
  projecao e escrita para a malha inteira, inclusive o corpo (1,38M vertices),
  que nao a amostra — 12,7 MB de dado morto no arquivo *sem compressao*. Depois
  do Draco isso custa **48 bytes**: o codificador reduz um atributo praticamente
  constante a quase nada. Separar a malha por material para eliminar 48 bytes
  nao paga o risco de mexer no grafo de cena.

Sobre o decodificador: `KHR_draco_mesh_compression` exige que o visualizador
carregue um decodificador WASM. O model-viewer busca em `gstatic.com` por
padrao, o que quebraria o app sem internet — por isso o backend serve uma copia
em `/files/draco/` e o app aponta para la (ver docs/17).

Roda dentro do Blender headless:

    blender.exe --background --python optimize_glb.py -- \\
        --input  path/to/with_top.glb \\
        --output path/to/final.glb \\
        [--position-quantization 14] [--texcoord-quantization 12]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # noqa: E402


def log(mensagem: str) -> None:
    print(f"[optimize_glb] {mensagem}", flush=True)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Comprime um GLB com Draco.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compression-level", type=int, default=6)
    # 14 bits de posicao = 16.384 passos no maior eixo do frasco. Num objeto de
    # ~10 cm isso da ~6 micrometros; muito abaixo do que a malha do Hunyuan
    # resolve, entao a quantizacao nao e o fator limitante da fidelidade.
    parser.add_argument("--position-quantization", type=int, default=14)
    parser.add_argument("--normal-quantization", type=int, default=10)
    parser.add_argument("--texcoord-quantization", type=int, default=12)
    return parser.parse_args(argv)


def importar(caminho: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(caminho))
    malhas = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not malhas:
        raise RuntimeError(f"GLB sem meshes: {caminho}")
    vertices = sum(len(o.data.vertices) for o in malhas)
    poligonos = sum(len(o.data.polygons) for o in malhas)
    log(f"entrada: {len(malhas)} mesh(es), {vertices:,} vertices, {poligonos:,} poligonos")


def exportar(args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=args.compression_level,
        export_draco_position_quantization=args.position_quantization,
        export_draco_normal_quantization=args.normal_quantization,
        export_draco_texcoord_quantization=args.texcoord_quantization,
    )


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        log(f"ERRO: GLB de entrada nao encontrado: {args.input}")
        return 1

    antes = args.input.stat().st_size
    importar(args.input)
    exportar(args)

    if not args.output.exists():
        log("ERRO: exportacao nao produziu arquivo")
        return 1

    depois = args.output.stat().st_size
    fator = antes / depois if depois else 0.0
    log(
        f"OK — {antes / 1e6:.1f} MB -> {depois / 1e6:.1f} MB "
        f"({fator:.1f}x, -{100 * (1 - depois / antes):.0f}%)"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — o exit code e o contrato com o wrapper
        log(f"ERRO: {exc}")
        sys.exit(1)
