"""Gera o template procedural `feeling_rectangular_blue.glb` (V2).

Roda dentro do Blender em modo headless:

    blender.exe --background --python generate_feeling_template.py --

Diferenças do V1 (que ficava com aparência de cubos empilhados):
- Bevels nas arestas do corpo, da tampa e da base — visual mais próximo do
  frasco real do Hinode Feelin' Flame.
- Gradiente azul→preto: o corpo é um vidro azul transparente, e dentro dele
  fica uma "Details" opaca preta cobrindo ~35% da altura — o que dá o efeito
  visual de gradiente quando renderizado.
- Tampa proporcional (mais alta, levemente mais larga e mais profunda que
  o corpo), com leve chamfer.
- Label única com a textura PNG dourada (`feeling_rectangular_blue_label.png`)
  aplicada — substitui os 3 meshes de texto que o V1 carregava ("Feeling",
  "HINODE", "FOR HIM").

A convenção de nomes/materiais segue o que o `customize_template.py` espera:
- Nó `Bottle` → corpo do frasco (vidro)
- Nó `Liquid` → líquido (recebe `--liquid-color` em runtime)
- Nó `Cap`     → tampa
- Nó `Details` → base preta interna (não tem role no customize)
- Nó `Label`   → plano frontal com material `LabelMaterial`

Saída: `back/assets/templates/normalized/feeling_rectangular_blue.glb`
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)


SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent.parent
NORMALIZED_DIR = BACK_ROOT / "assets" / "templates" / "normalized"
LABEL_PNG = NORMALIZED_DIR / "feeling_rectangular_blue_label.png"
OUTPUT_GLB = NORMALIZED_DIR / "feeling_rectangular_blue.glb"


# ---------------------------------------------------------------- dimensões
# Mantém escala próxima do V1 (altura total ~3.2) pra reaproveitar a câmera
# default do model-viewer. Authoring é em Blender (Z-up): X=largura,
# Y=profundidade, Z=altura. O exporter de glTF converte para Y-up no GLB.

BOTTLE = {
    "size": (1.22, 0.56, 2.50),       # X (largura), Y (profundidade), Z (altura)
    "center": (0.0, 0.0, 1.25),       # base do frasco em z=0
    "bevel": 0.06,
    "bevel_segments": 4,
}

LIQUID = {
    "size": (1.10, 0.45, 2.05),
    "center": (0.0, 0.0, 1.10),       # encostada no fundo, com headroom no topo
    "bevel": 0.04,
    "bevel_segments": 3,
}

DETAILS = {
    "size": (1.16, 0.50, 0.90),       # base preta cobrindo ~35% da altura
    "center": (0.0, 0.0, 0.45),       # encostada no fundo
    "bevel": 0.03,
    "bevel_segments": 2,
}

CAP = {
    "size": (1.32, 0.62, 0.65),       # ligeiramente maior que o corpo
    "center": (0.0, 0.0, 2.83),       # repousa em cima do corpo (z_top=2.50 + half=0.325)
    "bevel": 0.08,
    "bevel_segments": 5,
}

LABEL = {
    "size": (0.95, 1.55),             # plano vertical (X largura × Z altura)
    "center": (0.0, -0.288, 1.20),    # encostado na face frontal do corpo (Y- = frente)
}


# ---------------------------------------------------------------- materiais
# (r, g, b, a) e parâmetros do Principled BSDF.

GLASS_RGBA = (0.05, 0.18, 0.42, 0.62)
WATER_RGBA = (0.04, 0.16, 0.36, 0.85)
DARK_BASE_RGBA = (0.010, 0.012, 0.022, 1.0)   # preto azulado opaco
PLASTIC_RGBA = (0.012, 0.012, 0.014, 1.0)     # tampa preta levemente brilhante


# --------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[feeling] {msg}", flush=True)


def reset_scene() -> None:
    log("Limpando cena padrão")
    bpy.ops.wm.read_factory_settings(use_empty=True)


def add_box(
    name: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    bevel: float,
    bevel_segments: int,
) -> bpy.types.Object:
    """Cria um cubo no centro indicado, redimensiona, aplica scale e bevel."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if bevel > 0 and bevel_segments > 0:
        mod = obj.modifiers.new(name="Bevel", type="BEVEL")
        mod.width = bevel
        mod.segments = bevel_segments
        mod.limit_method = "ANGLE"
        mod.angle_limit = 0.7  # ~40° pega todas as arestas externas
        bpy.ops.object.modifier_apply(modifier=mod.name)

    return obj


def add_label_plane(name: str, size: tuple[float, float], center: tuple[float, float, float]) -> bpy.types.Object:
    """Plano frontal: rotacionado 90° em X (normal apontando para -Y, face frontal
    do bottle no sistema Z-up de autoria). O exporter glTF cuida da conversão.
    `size` é (largura X, altura Z) — após rotação, scale Z mapeia em altura.

    UVs são setadas manualmente em [0,1] × [0,1] para garantir que a textura
    da label ocupa toda a face do plano. O `bpy.ops.uv.unwrap(ANGLE_BASED)`
    preserva aspect ratio do mundo e acaba mapeando a textura em apenas
    metade do plano quando a relação largura/altura é diferente da textura.
    """
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.rotation_euler = (1.5707963267948966, 0.0, 0.0)
    obj.scale = (size[0], size[1], 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # UV manual: ordem dos loops = ordem das vertices na primitive_plane_add.
    # Vertices iniciais (em mesh local antes do scale/rotation):
    #   v0=(-0.5,-0.5,0)  v1=(+0.5,-0.5,0)  v2=(+0.5,+0.5,0)  v3=(-0.5,+0.5,0)
    # Mapeamos vértice "esquerdo-baixo" do plano em mundo → UV (0,0), e
    # "direito-cima" → UV (1,1). Após a rotação 90° em X o vértice v3 do
    # mesh fica no topo-esquerdo do mundo, então a ordem fica espelhada.
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data

    # Ordem de loops no quad é a mesma das vértices: v0, v1, v2, v3.
    # Coords-mundo de cada vértice (após rotation+scale aplicado):
    #   v0 → mundo (-W/2, 0, -H/2)  → bottom-left  → UV (0,0)
    #   v1 → mundo (+W/2, 0, -H/2)  → bottom-right → UV (1,0)
    #   v2 → mundo (+W/2, 0, +H/2)  → top-right    → UV (1,1)
    #   v3 → mundo (-W/2, 0, +H/2)  → top-left     → UV (0,1)
    target_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for i, uv in enumerate(target_uvs):
        uv_layer[i].uv = uv

    return obj


def make_material(
    name: str,
    base_rgba: tuple[float, float, float, float],
    *,
    roughness: float = 0.2,
    metallic: float = 0.0,
    transmission: float = 0.0,
    alpha_blend: bool = False,
    double_sided: bool = True,
) -> bpy.types.Material:
    """Cria material Principled BSDF parametrizado."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = base_rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = base_rgba[3]
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = transmission
    mat.use_backface_culling = not double_sided
    if alpha_blend:
        # Em Blender 4+ a propriedade ficou em surface_render_method; em 3.x
        # era blend_method. Tentamos os dois pra ser tolerante.
        try:
            mat.surface_render_method = "BLENDED"
        except (AttributeError, TypeError):
            try:
                mat.blend_method = "BLEND"
            except (AttributeError, TypeError):
                pass
    return mat


def make_label_material(name: str, image_path: Path) -> bpy.types.Material:
    """Material da label: textura PNG → Base Color, alpha do PNG → Alpha."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["Metallic"].default_value = 0.20

    image = bpy.data.images.load(str(image_path), check_existing=True)
    tex = tree.nodes.new(type="ShaderNodeTexImage")
    tex.image = image
    tex.location = (bsdf.location.x - 400, bsdf.location.y)
    tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in bsdf.inputs:
        tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])

    # Recorta áreas transparentes: usa MASK pra evitar artefato de blend
    # contra o vidro semi-transparente atrás da label.
    try:
        mat.surface_render_method = "DITHERED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "CLIP"
        except (AttributeError, TypeError):
            pass
    return mat


def assign_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


# ----------------------------------------------------------------- export

def export_glb(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Exportando: {output}")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )


def list_objects() -> None:
    log("=== objetos finais ===")
    for obj in bpy.data.objects:
        log(f"  {obj.type}: '{obj.name}' (mats={[m.name for m in obj.data.materials] if obj.type == 'MESH' else '-'})")


# -------------------------------------------------------------------- main

def main() -> int:
    if not LABEL_PNG.exists():
        raise FileNotFoundError(
            f"Label PNG ausente: {LABEL_PNG}. Rode primeiro `python scripts/build_feeling_label.py`."
        )

    log(f"label   = {LABEL_PNG}")
    log(f"output  = {OUTPUT_GLB}")

    reset_scene()

    # Materiais (criados antes pra reutilizar entre objetos).
    glass_mat = make_material(
        "Glass",
        GLASS_RGBA,
        roughness=0.10,
        transmission=0.85,
        alpha_blend=True,
    )
    water_mat = make_material(
        "water",
        WATER_RGBA,
        roughness=0.06,
        transmission=0.70,
        alpha_blend=True,
    )
    dark_mat = make_material(
        "DarkBlueBase",
        DARK_BASE_RGBA,
        roughness=0.32,
    )
    plastic_mat = make_material(
        "Plastic",
        PLASTIC_RGBA,
        roughness=0.18,
        metallic=0.05,
    )
    label_mat = make_label_material("LabelMaterial", LABEL_PNG)

    # Geometria.
    bottle = add_box("Bottle", **BOTTLE)
    assign_material(bottle, glass_mat)

    liquid = add_box("Liquid", **LIQUID)
    assign_material(liquid, water_mat)

    details = add_box("Details", **DETAILS)
    assign_material(details, dark_mat)

    cap = add_box("Cap", **CAP)
    assign_material(cap, plastic_mat)

    label = add_label_plane("Label", LABEL["size"], LABEL["center"])
    assign_material(label, label_mat)

    list_objects()
    export_glb(OUTPUT_GLB)
    log("OK — template gerado")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
