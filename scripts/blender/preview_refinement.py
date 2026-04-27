"""Renderiza comparacao lado a lado de um GLB cru e um GLB refinado.

Uso:

    blender.exe --background --python preview_refinement.py -- \
        --before raw_hunyuan.glb \
        --after refined.glb \
        --output comparison_before_after.png

O setup de camera, luz e Cycles segue o preview_feeling_template.py para manter
comparacoes visuais reprodutiveis nos slides do TCC.
"""

from __future__ import annotations

import argparse
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402


DEFAULT_OUTPUT = Path("comparison_before_after.png")


def log(msg: str) -> None:
    print(f"[preview-refinement] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def importar_glb(path: Path, prefixo: str) -> list[bpy.types.Object]:
    if not path.exists():
        raise FileNotFoundError(f"GLB nao encontrado: {path}")

    antes = set(bpy.data.objects)
    log(f"importando {prefixo}: {path}")
    bpy.ops.import_scene.gltf(filepath=str(path))

    novos = [obj for obj in bpy.data.objects if obj not in antes]
    for obj in novos:
        obj.name = f"{prefixo}_{obj.name}"
    return [obj for obj in novos if obj.type == "MESH"]


def calcular_bounds(objetos: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    pontos: list[Vector] = []
    for obj in objetos:
        if obj.type != "MESH" or not obj.bound_box:
            continue
        pontos.extend(obj.matrix_world @ Vector(canto) for canto in obj.bound_box)

    if not pontos:
        origem = Vector((0.0, 0.0, 0.0))
        return origem, origem

    minimo = Vector(
        (
            min(p.x for p in pontos),
            min(p.y for p in pontos),
            min(p.z for p in pontos),
        )
    )
    maximo = Vector(
        (
            max(p.x for p in pontos),
            max(p.y for p in pontos),
            max(p.z for p in pontos),
        )
    )
    return minimo, maximo


def normalizar_grupo(
    objetos: list[bpy.types.Object],
    *,
    centro_x: float,
    altura_alvo: float = 2.7,
) -> None:
    minimo, maximo = calcular_bounds(objetos)
    dimensoes = maximo - minimo
    altura = max(dimensoes.z, 0.001)
    escala = altura_alvo / altura
    centro_atual = (minimo + maximo) * 0.5
    destino = Vector((centro_x, 0.0, altura_alvo / 2.0))

    transformacao = (
        Matrix.Translation(destino)
        @ Matrix.Scale(escala, 4)
        @ Matrix.Translation(-centro_atual)
    )
    for obj in objetos:
        obj.matrix_world = transformacao @ obj.matrix_world


def configurar_camera_e_luzes() -> None:
    bpy.ops.object.empty_add(location=(0.0, 0.0, 1.30))
    alvo = bpy.context.object
    alvo.name = "PreviewTarget"

    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 55
    cam_obj = bpy.data.objects.new("PreviewCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = (1.6, -7.2, 2.1)
    bpy.context.scene.camera = cam_obj

    constraint = cam_obj.constraints.new(type="TRACK_TO")
    constraint.target = alvo
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 4.5
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = (3, -4, 6)
    sun.rotation_euler = (radians(45), radians(10), radians(40))

    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 450.0
    fill_data.size = 4.0
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = (-2.5, -3, 2)
    fill.rotation_euler = (radians(70), 0, radians(-30))

    rim_data = bpy.data.lights.new("Rim", type="AREA")
    rim_data.energy = 200.0
    rim_data.size = 3.0
    rim = bpy.data.objects.new("Rim", rim_data)
    bpy.context.collection.objects.link(rim)
    rim.location = (0, 4, 3)
    rim.rotation_euler = (radians(110), 0, radians(180))

    mundo = bpy.context.scene.world
    if mundo is None:
        mundo = bpy.data.worlds.new("PreviewWorld")
        bpy.context.scene.world = mundo
    mundo.use_nodes = True
    bg = mundo.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.965, 0.94, 0.95, 1.0)
        bg.inputs["Strength"].default_value = 1.4


def configurar_render(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.samples = 64
    cena.cycles.use_denoising = True
    cena.render.resolution_x = 1440
    cena.render.resolution_y = 1080
    cena.render.image_settings.file_format = "PNG"
    cena.render.filepath = str(output)


def main() -> int:
    parser = argparse.ArgumentParser(prog="preview_refinement")
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(get_argv_after_double_dash())

    bpy.ops.wm.read_factory_settings(use_empty=True)

    objetos_before = importar_glb(args.before, "Before")
    objetos_after = importar_glb(args.after, "After")
    normalizar_grupo(objetos_before, centro_x=-1.15)
    normalizar_grupo(objetos_after, centro_x=1.15)

    configurar_camera_e_luzes()
    configurar_render(args.output)

    log(f"renderizando -> {args.output}")
    bpy.ops.render.render(write_still=True)
    log("OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
