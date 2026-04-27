"""Normaliza templates 3D brutos (Sketchfab) para uso pelo TemplateProcessor.

Roda dentro do Blender (headless):

    blender.exe --background --python normalize_template.py -- --template-id <id>
    blender.exe --background --python normalize_template.py -- --all

Cada template tem uma entrada em `TEMPLATES` que descreve a estratégia de
normalização. Convenção de saída:
- Nós obrigatórios: Bottle, Cap, Label (Liquid/Details opcionais)
- Origem (0,0,0); altura Z = 1.0; orientação Y-up no GLB exportado
- Material `LabelMaterial` com slot vazio para textura em runtime

Saída: `back/assets/templates/normalized/<template_id>.glb`
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)


SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent.parent
RAW_BASE = BACK_ROOT / "assets" / "templates" / "raw"
OUTPUT_DIR = BACK_ROOT / "assets" / "templates" / "normalized"


# Estratégias suportadas:
#   "material" — usa material_map (nome → "Bottle"/"Cap"/"Liquid"/"Label")
#   "single"   — todos os meshes viram um único `Bottle`
#   "bbox"     — heurística geométrica: maior mesh (altura) = Bottle,
#                meshes acima dele = Cap

TEMPLATES = {
    "rectangular_basic": {
        "raw_subdir": "rectangular/rectangular_basic",
        "strategy": "material",
        "material_map": {
            "Glass": "Bottle",
            "water": "Liquid",
            "Plastic": "Cap",
        },
        "detail_materials": ["Gloss", "Material", "void", "Spring"],
    },
    "cylindrical_basic": {
        "raw_subdir": "cylindrical/cylindrical_basic",
        "strategy": "material",
        "material_map": {
            "Material.002": "Bottle",
            "Material.001": "Cap",
            "lebel": "Label",
        },
        "detail_materials": [],
        "skip_label_creation": True,  # template já traz label embutida
    },
    "square_compact": {
        "raw_subdir": "square/square_compact",
        "strategy": "single",  # 1 mesh, vira Bottle
    },
    "round_spherical": {
        "raw_subdir": "round/round_spherical",
        "strategy": "material",
        "material_map": {
            "Material.001": "Bottle",   # corpo cilíndrico
            "Material.003": "Cap",      # tampa esférica
        },
        "detail_materials": [],
    },
    "ornamental_modernist": {
        "raw_subdir": "ornamental/ornamental_modernist",
        "strategy": "single",  # 8 meshes todos com mesmo material → tudo junto
    },
}


# --------------------------------------------------------------------- log

def log(msg: str) -> None:
    print(f"[normalize] {msg}", flush=True)


# --------------------------------------------------------------- helpers

def reset_scene() -> None:
    log("Limpando cena padrão")
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_gltf(path: Path) -> None:
    log(f"Importando: {path}")
    if not path.exists():
        raise FileNotFoundError(f"glTF não encontrado: {path}")
    bpy.ops.import_scene.gltf(filepath=str(path))


def cleanup_non_mesh_nodes() -> None:
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            log(f"  removendo nó não-mesh: '{obj.name}' ({obj.type})")
            bpy.data.objects.remove(obj, do_unlink=True)


def get_first_material_base_name(obj: bpy.types.Object) -> str | None:
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if mat is None:
        return None
    return mat.name.split(".")[0] + (
        "." + mat.name.split(".")[1] if len(mat.name.split(".")) > 1 and mat.name.split(".")[1].isdigit() else ""
    )


def get_first_material_full_name(obj: bpy.types.Object) -> str | None:
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    return mat.name if mat else None


# ---------------------------------------------------- estratégias

def group_by_material_strategy(config: dict) -> dict[str, list[bpy.types.Object]]:
    """Agrupa por nome do material conforme `material_map`."""
    material_map: dict[str, str] = config["material_map"]
    detail_materials = set(config.get("detail_materials", []))

    groups: dict[str, list[bpy.types.Object]] = {
        "Bottle": [], "Liquid": [], "Cap": [], "Label": [], "Detail": []
    }

    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        mat_name = get_first_material_full_name(obj) or ""
        # tenta nome exato, depois sem o sufixo .001
        base = mat_name.split(".")[0]

        role = material_map.get(mat_name) or material_map.get(base)
        if role:
            groups[role].append(obj)
        elif base in detail_materials:
            groups["Detail"].append(obj)
        else:
            log(f"  AVISO: material '{mat_name}' sem role mapeado — vai pra Details")
            groups["Detail"].append(obj)

    return groups


def group_by_single_strategy(config: dict) -> dict[str, list[bpy.types.Object]]:
    """Joga tudo num único `Bottle`. Bom pra modelos com 1 mat ou peças indistinguíveis."""
    groups: dict[str, list[bpy.types.Object]] = {
        "Bottle": [], "Liquid": [], "Cap": [], "Label": [], "Detail": []
    }
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            groups["Bottle"].append(obj)
    return groups


def group_meshes(config: dict) -> dict[str, list[bpy.types.Object]]:
    strategy = config["strategy"]
    if strategy == "material":
        return group_by_material_strategy(config)
    if strategy == "single":
        return group_by_single_strategy(config)
    raise ValueError(f"strategy desconhecida: {strategy}")


# ------------------------------------------------------------ join/transform

def join_objects(objects: list[bpy.types.Object], new_name: str) -> bpy.types.Object | None:
    if not objects:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active
    merged.name = new_name
    if merged.data:
        merged.data.name = new_name
    log(f"  joined -> '{new_name}' ({len(objects)} meshes)")
    return merged


def _aggregate_bbox():
    from mathutils import Vector

    min_v = [float("inf")] * 3
    max_v = [float("-inf")] * 3
    for obj in bpy.context.selected_objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for i in range(3):
                if world[i] < min_v[i]:
                    min_v[i] = world[i]
                if world[i] > max_v[i]:
                    max_v[i] = world[i]
    size = [max_v[i] - min_v[i] for i in range(3)]
    center = [(max_v[i] + min_v[i]) / 2 for i in range(3)]
    return min_v, max_v, size, center


def reorient_to_z_up() -> None:
    bpy.ops.object.select_all(action="SELECT")
    if not bpy.context.selected_objects:
        return

    _, _, size, _ = _aggregate_bbox()
    height_axis = max(range(3), key=lambda i: size[i])
    log(f"  altura detectada antes da rotação: eixo {'XYZ'[height_axis]} ({size[height_axis]:.3f})")

    if height_axis == 2:
        log("  já em Z-up — sem rotação")
        return

    angle = math.pi / 2
    if height_axis == 0:
        bpy.ops.transform.rotate(value=-angle, orient_axis="Y")
    else:
        bpy.ops.transform.rotate(value=angle, orient_axis="X")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def center_and_normalize_scale(target_height: float = 1.0) -> None:
    bpy.ops.object.select_all(action="SELECT")
    if not bpy.context.selected_objects:
        return

    _, _, size, center = _aggregate_bbox()
    z_size = size[2] if size[2] > 0 else 1.0
    factor = target_height / z_size

    for obj in bpy.context.selected_objects:
        obj.location.x -= center[0]
        obj.location.y -= center[1]
        obj.location.z -= center[2]

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.transform.resize(value=(factor, factor, factor))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    log(f"  scale={factor:.4f}, altura final Z=~{target_height}")


# ---------------------------------------------------------------- label

def _world_bbox(obj: bpy.types.Object):
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def add_label_plane(bottle: bpy.types.Object) -> bpy.types.Object | None:
    if bottle is None:
        log("  AVISO: sem Bottle — pulando criação de Label")
        return None

    min_v, max_v = _world_bbox(bottle)
    bottle_h = max_v[2] - min_v[2]
    bottle_w = max_v[0] - min_v[0]

    label_w = bottle_w * 0.65
    label_h = bottle_h * 0.40
    label_y = min_v[1] - 0.001
    label_x = (min_v[0] + max_v[0]) / 2
    label_z = (min_v[2] + max_v[2]) / 2

    bpy.ops.mesh.primitive_plane_add(size=1, location=(label_x, label_y, label_z))
    plane = bpy.context.object
    plane.name = "Label"
    plane.data.name = "Label"
    plane.rotation_euler = (math.pi / 2, 0, 0)
    plane.dimensions = (label_w, 0, label_h)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    bpy.ops.object.select_all(action="DESELECT")
    plane.select_set(True)
    bpy.context.view_layer.objects.active = plane
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED")
    bpy.ops.object.mode_set(mode="OBJECT")

    mat = bpy.data.materials.new(name="LabelMaterial")
    mat.use_nodes = True
    plane.data.materials.append(mat)

    log(f"  criado Label: {label_w:.3f} x {label_h:.3f}")
    return plane


def rename_existing_label_material(label_obj: bpy.types.Object) -> None:
    """Quando o template já tem mesh `Label`, garante que seu material chame
    `LabelMaterial` para o customize_template.py encontrá-lo."""
    if label_obj is None or not label_obj.data.materials:
        return
    mat = label_obj.data.materials[0]
    if mat is not None and mat.name != "LabelMaterial":
        log(f"  renomeando material '{mat.name}' -> 'LabelMaterial'")
        mat.name = "LabelMaterial"


# ----------------------------------------------------------------- export

def export_glb(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Exportando GLB: {output}")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )


def list_final_objects() -> None:
    log("=== objetos finais ===")
    for obj in bpy.data.objects:
        log(f"  {obj.type}: '{obj.name}'")


# -------------------------------------------------------------- driver

def normalize_one(template_id: str) -> None:
    if template_id not in TEMPLATES:
        raise KeyError(f"template_id desconhecido: {template_id}. Conhecidos: {list(TEMPLATES)}")

    config = TEMPLATES[template_id]
    raw_path = RAW_BASE / config["raw_subdir"] / "scene.gltf"
    output_path = OUTPUT_DIR / f"{template_id}.glb"

    log(f"=== Normalizando '{template_id}' ===")
    log(f"  raw    = {raw_path}")
    log(f"  output = {output_path}")
    log(f"  strategy = {config['strategy']}")

    reset_scene()
    import_gltf(raw_path)
    cleanup_non_mesh_nodes()

    groups = group_meshes(config)
    log(
        "  meshes por papel: "
        + ", ".join(f"{k}={len(v)}" for k, v in groups.items())
    )

    bottle = join_objects(groups["Bottle"], "Bottle")
    join_objects(groups["Liquid"], "Liquid")
    join_objects(groups["Cap"], "Cap")
    if groups["Detail"]:
        join_objects(groups["Detail"], "Details")

    existing_label = join_objects(groups["Label"], "Label") if groups.get("Label") else None
    if existing_label is not None:
        rename_existing_label_material(existing_label)

    reorient_to_z_up()
    center_and_normalize_scale(target_height=1.0)

    if existing_label is None and not config.get("skip_label_creation", False):
        add_label_plane(bottle)
    elif existing_label is None and config.get("skip_label_creation"):
        log("  skip_label_creation=True mas template não trouxe Label — criando mesmo assim")
        add_label_plane(bottle)

    list_final_objects()
    export_glb(output_path)
    log(f"=== OK '{template_id}' ===\n")


def main() -> int:
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(prog="normalize_template")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--template-id", choices=list(TEMPLATES.keys()))
    g.add_argument("--all", action="store_true", help="Normaliza todos os templates registrados")
    args = parser.parse_args(argv)

    if args.all:
        for tid in TEMPLATES:
            normalize_one(tid)
    else:
        normalize_one(args.template_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
