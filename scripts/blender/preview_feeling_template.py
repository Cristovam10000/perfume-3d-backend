"""Renderiza um preview PNG do template `feeling_rectangular_blue.glb`.

Útil para inspecionar visualmente o template sem precisar abrir o
model-viewer ou o app. Executar:

    blender.exe --background --python preview_feeling_template.py -- \
        --output back/assets/templates/normalized/feeling_rectangular_blue_preview.png

Câmera/luz são fixas para reprodutibilidade do preview.
"""

from __future__ import annotations

import argparse
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent.parent
DEFAULT_TEMPLATE = (
    BACK_ROOT / "assets" / "templates" / "normalized" / "feeling_rectangular_blue.glb"
)
DEFAULT_OUTPUT = (
    BACK_ROOT / "assets" / "templates" / "normalized" / "feeling_rectangular_blue_preview.png"
)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def main() -> int:
    parser = argparse.ArgumentParser(prog="preview_feeling_template")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(get_argv_after_double_dash())

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.template))

    # Câmera 3/4 frontal — replica grosso modo o ângulo padrão do
    # model-viewer (`camera-orbit="35deg 70deg 105%"`).
    bpy.ops.object.empty_add(location=(0.0, 0.0, 1.30))
    target = bpy.context.object
    target.name = "PreviewTarget"

    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 60
    cam_obj = bpy.data.objects.new("PreviewCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = (1.4, -5.6, 1.9)
    bpy.context.scene.camera = cam_obj

    constraint = cam_obj.constraints.new(type="TRACK_TO")
    constraint.target = target
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

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("PreviewWorld")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.965, 0.94, 0.95, 1.0)  # rosa claro do app
        bg.inputs["Strength"].default_value = 1.4

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 1080
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(args.output)

    print(f"[preview] renderizando -> {args.output}", flush=True)
    bpy.ops.render.render(write_still=True)
    print("[preview] OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[preview] ERRO: {exc}", flush=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)
