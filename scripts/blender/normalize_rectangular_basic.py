"""Normaliza o template `rectangular_basic` para uso pelo TemplateProcessor.

Roda dentro do Blender (headless):

    blender.exe --background --python normalize_rectangular_basic.py

Não recebe argumentos — caminhos são resolvidos a partir da localização do
script. Saída esperada:

    back/assets/templates/normalized/rectangular_basic.glb

O script é idempotente: pode ser rodado várias vezes que o resultado é o mesmo.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)


# ----------------------------------------------------------------------------
# Resolução de caminhos a partir da localização deste arquivo:
#   back/scripts/blender/normalize_rectangular_basic.py
# back root é três níveis acima.

SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent.parent
RAW_GLTF = (
    BACK_ROOT
    / "assets"
    / "templates"
    / "raw"
    / "rectangular"
    / "rectangular_basic"
    / "scene.gltf"
)
OUTPUT_DIR = BACK_ROOT / "assets" / "templates" / "normalized"
OUTPUT_GLB = OUTPUT_DIR / "rectangular_basic.glb"


# ----------------------------------------------------------------------------
# Mapeamento de materiais → papel semântico no nosso template.
# A heurística é olhar o nome do material; ajusta aqui se um template novo
# usar nomes diferentes.

MATERIAL_TO_ROLE = {
    "Glass": "Bottle",
    "water": "Liquid",
    "Plastic": "Cap",
}

# Materiais "decorativos" — meshes com esses materiais ficam num grupo
# `Details` que o customize_template.py NÃO toca.
DETAIL_MATERIALS = {"Gloss", "Material", "void", "Spring"}


def log(msg: str) -> None:
    print(f"[normalize] {msg}", flush=True)


# ----------------------------------------------------------------------------
# Etapas

def reset_scene() -> None:
    """Apaga tudo que existe na cena padrão do Blender."""
    log("Limpando cena padrão")
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_gltf(path: Path) -> None:
    log(f"Importando: {path}")
    if not path.exists():
        raise FileNotFoundError(f"glTF de entrada não encontrado: {path}")
    bpy.ops.import_scene.gltf(filepath=str(path))


def get_role_of_object(obj: bpy.types.Object) -> str | None:
    """Retorna 'Bottle' / 'Liquid' / 'Cap' / 'Detail' / None pelo material."""
    if obj.type != "MESH" or not obj.data.materials:
        return None
    mat_name = obj.data.materials[0].name if obj.data.materials[0] else ""
    # Materiais do Blender podem vir com sufixo .001 etc. — base é antes do ponto.
    base = mat_name.split(".")[0]
    if base in MATERIAL_TO_ROLE:
        return MATERIAL_TO_ROLE[base]
    if base in DETAIL_MATERIALS:
        return "Detail"
    return None


def collect_meshes_by_role() -> dict[str, list[bpy.types.Object]]:
    groups: dict[str, list[bpy.types.Object]] = {
        "Bottle": [],
        "Liquid": [],
        "Cap": [],
        "Detail": [],
    }
    for obj in list(bpy.data.objects):
        role = get_role_of_object(obj)
        if role is None:
            continue
        groups[role].append(obj)
    log(
        "Meshes por papel: "
        + ", ".join(f"{k}={len(v)}" for k, v in groups.items())
    )
    return groups


def join_objects(objects: list[bpy.types.Object], new_name: str) -> bpy.types.Object | None:
    """Une vários meshes num único objeto chamado `new_name`. None se vazio."""
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
    log(f"  joined → '{new_name}' ({len(objects)} meshes consolidados)")
    return merged


def cleanup_non_mesh_nodes() -> None:
    """Remove empties/cameras/luzes herdados do gltf — só queremos as malhas."""
    for obj in list(bpy.data.objects):
        if obj.type not in ("MESH",):
            log(f"  removendo nó não-mesh: '{obj.name}' ({obj.type})")
            bpy.data.objects.remove(obj, do_unlink=True)


def _aggregate_bbox():
    """Bounding box agregado de todos os objetos selecionados, em world space."""
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
    """Garante que a altura do frasco está no eixo Z (convenção Blender).

    Modelos do Sketchfab vindos de FBX tendem a chegar deitados — a altura
    aparece em Y. Detectamos o eixo de maior dimensão (= altura do frasco)
    e rotacionamos a cena pra que ele vire Z.
    """
    bpy.ops.object.select_all(action="SELECT")
    if not bpy.context.selected_objects:
        return

    _, _, size, _ = _aggregate_bbox()
    height_axis = max(range(3), key=lambda i: size[i])
    log(f"  eixo de altura detectado pré-rotação: {'XYZ'[height_axis]} ({size[height_axis]:.3f})")

    if height_axis == 2:
        log("  já está em Z-up — sem rotação")
        return

    # Rotação para levar o eixo de altura ao Z.
    angle = math.pi / 2  # 90°
    if height_axis == 0:
        # X-up → Z-up: rotaciona em Y
        bpy.ops.transform.rotate(value=-angle, orient_axis="Y")
    else:
        # Y-up → Z-up: rotaciona em X
        bpy.ops.transform.rotate(value=angle, orient_axis="X")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    log(f"  rotação aplicada para levar eixo {'XYZ'[height_axis]} ao Z")


def center_and_normalize_scale(target_height: float = 1.0) -> None:
    """Centraliza no origin e escala pra que a altura total (Z) seja `target_height`.

    Pré-condição: chamar `reorient_to_z_up()` antes pra garantir altura no Z.
    """
    bpy.ops.object.select_all(action="SELECT")
    if not bpy.context.selected_objects:
        return

    _, _, size, center = _aggregate_bbox()
    log(f"  bbox pós-rotação: size={size}, center={center}")

    z_size = size[2] if size[2] > 0 else 1.0
    factor = target_height / z_size

    for obj in bpy.context.selected_objects:
        obj.location.x -= center[0]
        obj.location.y -= center[1]
        obj.location.z -= center[2]

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.transform.resize(value=(factor, factor, factor))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    log(f"  scale uniforme = {factor:.4f} (altura final Z ≈ {target_height})")


def add_label_plane(bottle: bpy.types.Object) -> bpy.types.Object | None:
    """Cria um plano 'Label' colado na frente (-Y) do Bottle, com UV pronta.

    Convenção pós-normalização: Z = altura, X = largura, Y = profundidade.
    Frente do frasco = lado de menor Y. A Label é um plano fino vertical
    (XZ) posicionado um épsilon à frente do bbox.
    """
    if bottle is None:
        log("  AVISO: Bottle não existe, pulando criação de Label")
        return None

    min_v, max_v = _world_bbox(bottle)
    bottle_height = max_v[2] - min_v[2]
    bottle_width = max_v[0] - min_v[0]

    label_w = bottle_width * 0.65
    label_h = bottle_height * 0.40
    label_y = min_v[1] - 0.001
    label_x = (min_v[0] + max_v[0]) / 2
    label_z = (min_v[2] + max_v[2]) / 2

    bpy.ops.mesh.primitive_plane_add(size=1, location=(label_x, label_y, label_z))
    plane = bpy.context.object
    plane.name = "Label"
    plane.data.name = "Label"  # também renomeia o mesh data, não só o objeto

    # Plane primitive nasce no plano XY (horizontal); rotacionamos pra ficar
    # vertical voltada pra -Y (frente).
    plane.rotation_euler = (math.pi / 2, 0, 0)
    plane.dimensions = (label_w, 0, label_h)

    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # UV unwrap simples (cada vértice mapeia ao quadrado [0,1]).
    bpy.ops.object.select_all(action="DESELECT")
    plane.select_set(True)
    bpy.context.view_layer.objects.active = plane
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED")
    bpy.ops.object.mode_set(mode="OBJECT")

    # Material placeholder. O TemplateProcessor (E10) vai substituir a textura
    # da label por uma imagem real do produto.
    mat = bpy.data.materials.new(name="LabelMaterial")
    mat.use_nodes = True
    plane.data.materials.append(mat)

    log(f"  criado Label: {label_w:.3f} × {label_h:.3f} na frente (-Y) do Bottle")
    return plane


def _world_bbox(obj: bpy.types.Object):
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


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


# ----------------------------------------------------------------------------
# Execução

def main() -> int:
    log(f"BACK_ROOT = {BACK_ROOT}")
    log(f"RAW       = {RAW_GLTF}")
    log(f"OUTPUT    = {OUTPUT_GLB}")

    reset_scene()
    import_gltf(RAW_GLTF)

    cleanup_non_mesh_nodes()

    groups = collect_meshes_by_role()

    bottle = join_objects(groups["Bottle"], "Bottle")
    liquid = join_objects(groups["Liquid"], "Liquid")
    cap = join_objects(groups["Cap"], "Cap")
    if groups["Detail"]:
        join_objects(groups["Detail"], "Details")

    reorient_to_z_up()
    center_and_normalize_scale(target_height=1.0)

    if bottle is not None:
        add_label_plane(bottle)

    list_final_objects()
    export_glb(OUTPUT_GLB)
    log("OK — normalização concluída")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
