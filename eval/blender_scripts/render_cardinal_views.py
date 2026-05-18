"""Renderiza 4 vistas cardeais de um GLB para alimentar pipelines como input sintético.

Convenção de eixos (Blender padrão):
- Frasco com base no plano XY, eixo Z = altura.
- Câmera olha para o origem; varia em torno do eixo Z (azimuth).

Vistas geradas:
- front : câmera em +Y, olhando para -Y  (vê a face +Y do frasco)
- right : câmera em +X, olhando para -X  (vê a face +X)
- back  : câmera em -Y, olhando para +Y  (vê a face -Y)
- left  : câmera em -X, olhando para +X  (vê a face -X)

A correspondência cardeal ⇄ direção segue a convenção do Hunyuan3D-2mv
(checkpoint multi-view). Quando o GLB de teste não está orientado da
mesma forma, --rotate-z permite girar antes de renderizar.

Roda em modo headless:

    blender.exe --background --python render_cardinal_views.py -- \\
        --input  template.glb \\
        --output-dir renders/ \\
        [--resolution 1024] \\
        [--rotate-z 0] \\
        [--bg-color 1.0,1.0,1.0]
"""

from __future__ import annotations

import argparse
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)
from mathutils import Vector  # noqa: E402


# --------------------------------------------------------------------- helpers


def log(msg: str) -> None:
    print(f"[render-views] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    # Tudo após '--' é nosso; Blender consome o resto.
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument(
        "--rotate-z",
        type=float,
        default=0.0,
        help="Rotação prévia do modelo em torno de Z (graus). Útil quando "
        "o frasco não está orientado com a frente em +Y.",
    )
    parser.add_argument(
        "--bg-color",
        type=str,
        default="1.0,1.0,1.0",
        help="RGB do fundo (0-1, vírgula).",
    )
    parser.add_argument(
        "--camera-distance-factor",
        type=float,
        default=2.5,
        help="Multiplica a diagonal da bbox para a distância da câmera.",
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: Path) -> Vector:
    """Importa GLB, centraliza na origem, escala para diagonal=2.0.

    Devolve a diagonal usada como referência para posicionar a câmera.
    """
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise RuntimeError(f"GLB sem meshes: {path}")

    # Combina bbox de todos os meshes
    min_v = Vector((float("inf"),) * 3)
    max_v = Vector((float("-inf"),) * 3)
    for obj in objs:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_v = Vector(min(a, b) for a, b in zip(min_v, world))
            max_v = Vector(max(a, b) for a, b in zip(max_v, world))

    centroid = (min_v + max_v) / 2
    diagonal = (max_v - min_v).length
    log(f"Bounding box: diagonal={diagonal:.3f}, centroid={tuple(centroid)}")

    # Centraliza e normaliza escala
    for obj in objs:
        obj.location -= centroid

    target_diagonal = 2.0
    scale = target_diagonal / diagonal if diagonal > 0 else 1.0
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.transform.resize(value=(scale, scale, scale))
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    return Vector((0, 0, 0))


def rotate_models(angle_deg: float) -> None:
    if angle_deg == 0:
        return
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.transform.rotate(value=radians(angle_deg), orient_axis="Z")
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)


def setup_world(bg_color: tuple[float, float, float]) -> None:
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node is not None:
        bg_node.inputs["Color"].default_value = (*bg_color, 1.0)
        bg_node.inputs["Strength"].default_value = 1.0


def setup_lighting() -> None:
    """Three-point lighting estilo estúdio."""
    for light_data in (
        ("Key", (3.0, -3.0, 4.0), 1000.0),
        ("Fill", (-3.0, -2.0, 2.0), 500.0),
        ("Back", (0.0, 4.0, 3.0), 700.0),
    ):
        name, loc, energy = light_data
        light = bpy.data.lights.new(name=name, type="AREA")
        light.energy = energy
        light.size = 2.5
        obj = bpy.data.objects.new(name=name, object_data=light)
        obj.location = loc
        bpy.context.collection.objects.link(obj)


def create_camera(distance: float):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 50  # mm
    cam_obj = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    return cam_obj


def look_at(cam_obj, target: Vector) -> None:
    direction = target - cam_obj.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()


def configure_render(resolution: int) -> None:
    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.engine = "BLENDER_EEVEE"
    # Eevee config (rápido, pra dataset rolar em segundos por vista).
    try:
        scene.eevee.taa_render_samples = 64
        scene.eevee.use_gtao = True
    except AttributeError:
        # Blender 4.2+ usa eevee_next
        pass


def render_view(cam_obj, name: str, position: Vector, target: Vector, out_dir: Path) -> Path:
    cam_obj.location = position
    look_at(cam_obj, target)
    out_path = out_dir / f"{name}.png"
    bpy.context.scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    log(f"Renderizado: {name} → {out_path}")
    return out_path


# ----------------------------------------------------------------------- main


CARDINAL_POSITIONS = {
    "front": Vector((0.0, -1.0, 0.0)),  # câmera em -Y olhando +Y → vê face frontal
    "right": Vector((1.0, 0.0, 0.0)),
    "back": Vector((0.0, 1.0, 0.0)),
    "left": Vector((-1.0, 0.0, 0.0)),
}


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    bg_color = tuple(float(x) for x in args.bg_color.split(","))
    if len(bg_color) != 3:
        raise SystemExit("--bg-color precisa de 3 valores separados por vírgula")

    log(f"Carregando {args.input}")
    clear_scene()
    target = import_glb(args.input)
    rotate_models(args.rotate_z)

    setup_world(bg_color)
    setup_lighting()
    configure_render(args.resolution)

    distance = args.camera_distance_factor  # diagonal já é 2.0 após normalização
    cam = create_camera(distance)

    rendered: list[Path] = []
    for name, direction in CARDINAL_POSITIONS.items():
        position = direction * distance + Vector((0, 0, 0.1))  # leve elevação
        rendered.append(render_view(cam, name, position, target, args.output_dir))

    log(f"Concluído: {len(rendered)} vistas em {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
