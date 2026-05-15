"""Projeta a foto do topo do frasco diretamente nas faces superiores da tampa.

Em vez de criar um plano flutuante (decal), modifica o material das faces
superiores da tampa para exibir a imagem via projecao ortografica de cima.

Fluxo:
1. Importa o GLB.
2. Identifica o mesh de maior Z (a tampa).
3. Coleta as faces com normal apontando para cima (dot(n, Z) >= threshold).
4. Calcula coordenadas UV para essas faces via projecao ortografica: cada
   vertice recebe UV = ((x - min_x) / largura, (y - min_y) / altura).
5. Cria um novo UV map "TopProjectionUV" no mesh da tampa.
6. Adiciona a imagem como novo material ("TopTextureMaterial") e atribui
   apenas as faces superiores a esse material.
7. Exporta GLB com a textura embutida.

Roda dentro do Blender headless:

    blender.exe --background --python project_top_texture.py -- \\
        --input  path/to/refined.glb \\
        --top    path/to/05_top_segmented.png \\
        --output path/to/with_top.glb \\
        [--cosine-threshold 0.5]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

UP_AXIS = Vector((0.0, 0.0, 1.0))


def log(msg: str) -> None:
    print(f"[project-top] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="project_top_texture")
    parser.add_argument("--input",  required=True, type=Path)
    parser.add_argument("--top",    required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cosine-threshold", type=float, default=0.45)
    return parser.parse_args(get_argv_after_double_dash())


# ------------------------------------------------------------------ geometria

def normal_mundo(obj: bpy.types.Object, poly: bpy.types.MeshPolygon) -> Vector:
    mat3 = obj.matrix_world.to_3x3().inverted().transposed()
    n = mat3 @ poly.normal
    return n.normalized() if n.length > 0 else UP_AXIS.copy()


def max_z_bbox(obj: bpy.types.Object) -> float:
    if not obj.bound_box:
        return obj.location.z
    return max((obj.matrix_world @ Vector(v)).z for v in obj.bound_box)


def identificar_tampa(meshes: list[bpy.types.Object]) -> bpy.types.Object | None:
    if not meshes:
        return None
    return max(meshes, key=max_z_bbox)


def coletar_faces_topo(
    obj: bpy.types.Object,
    threshold: float,
) -> list[bpy.types.MeshPolygon]:
    faces = [p for p in obj.data.polygons if normal_mundo(obj, p).dot(UP_AXIS) >= threshold]
    # Fallback progressivo se threshold alto demais
    for t in (0.35, 0.20, 0.0):
        if faces:
            break
        faces = [p for p in obj.data.polygons if normal_mundo(obj, p).dot(UP_AXIS) >= t]
        if faces and t < threshold:
            log(f"AVISO: threshold relaxado para {t} ({len(faces)} faces)")
    return faces


# ------------------------------------------------------------------ UV + material

def criar_material_topo(img_path: Path) -> bpy.types.Material:
    """Cria material com Image Texture RGBA (transparencia preservada)."""
    nome = "TopTextureMaterial"
    for mat in list(bpy.data.materials):
        if mat.name.split(".")[0] == nome:
            bpy.data.materials.remove(mat)

    imagem = bpy.data.images.load(str(img_path))
    try:
        imagem.pack()
    except RuntimeError:
        pass

    mat = bpy.data.materials.new(nome)
    mat.use_nodes = True
    mat.use_backface_culling = False

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    saida = nodes.new("ShaderNodeOutputMaterial")
    saida.location = (500, 0)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (300, 0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (100, -80)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 80)
    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-200, 80)
    tex.image = imagem
    tex.image.colorspace_settings.name = "sRGB"

    # Conecta: textura → BSDF (cor) + alpha → Mix (transparencia)
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(bsdf.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], saida.inputs["Surface"])

    try:
        mat.surface_render_method = "BLENDED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass

    return mat


def aplicar_uv_projecao_topo(
    obj: bpy.types.Object,
    faces_topo: list[bpy.types.MeshPolygon],
    img_path: Path,
) -> None:
    """
    Projeta UV ortograficamente nas faces do topo via coordenadas mundo XY.
    Cria material novo e o atribui apenas a essas faces.
    """
    mat_world = obj.matrix_world
    verts = obj.data.vertices

    # Coleta todos os vértices das faces do topo em coordenadas mundo
    indices_faces = {p.index for p in faces_topo}
    xs, ys = [], []
    for face in faces_topo:
        for vi in face.vertices:
            p = mat_world @ verts[vi].co
            xs.append(p.x)
            ys.append(p.y)

    if not xs:
        raise RuntimeError("nenhum vértice nas faces do topo")

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    log(f"bbox XY do topo: x=[{min_x:.3f},{max_x:.3f}] y=[{min_y:.3f},{max_y:.3f}]")

    # Cria ou substitui UV map "TopProjectionUV"
    uv_nome = "TopProjectionUV"
    if uv_nome in obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[uv_nome])
    uv_layer = obj.data.uv_layers.new(name=uv_nome)
    obj.data.uv_layers.active = uv_layer

    # Preenche UVs: faces do topo recebem projecao XY; restantes ficam em (0,0)
    for face in obj.data.polygons:
        if face.index in indices_faces:
            for loop_i, vi in zip(face.loop_indices, face.vertices):
                p = mat_world @ verts[vi].co
                u = (p.x - min_x) / span_x
                v = (p.y - min_y) / span_y
                uv_layer.data[loop_i].uv = (u, v)
        else:
            for loop_i in face.loop_indices:
                uv_layer.data[loop_i].uv = (0.0, 0.0)

    # Adiciona material novo ao objeto
    material = criar_material_topo(img_path)
    obj.data.materials.append(material)
    mat_idx = len(obj.data.materials) - 1

    # Atribui material apenas às faces do topo
    for face in obj.data.polygons:
        if face.index in indices_faces:
            face.material_index = mat_idx

    # Faz o UV map ativo usar o material correto
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            node.extension = "CLIP"

    log(f"UV projecao aplicada: {len(faces_topo)} faces, material_index={mat_idx}")


# ------------------------------------------------------------------ main

def main() -> int:
    args = parse_args()
    log(f"input             = {args.input}")
    log(f"top               = {args.top}")
    log(f"output            = {args.output}")
    log(f"cosine-threshold  = {args.cosine_threshold}")

    if not args.input.exists():
        raise FileNotFoundError(f"GLB nao encontrado: {args.input}")
    if not args.top.exists():
        raise FileNotFoundError(f"Imagem do topo nao encontrada: {args.top}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("GLB sem meshes")
    log(f"meshes: {[o.name for o in meshes]}")

    tampa = identificar_tampa(meshes)
    if tampa is None:
        raise RuntimeError("tampa nao identificada")
    log(f"tampa: '{tampa.name}' (max_z={max_z_bbox(tampa):.4f})")

    faces_topo = coletar_faces_topo(tampa, args.cosine_threshold)
    log(f"faces do topo: {len(faces_topo)}")

    if not faces_topo:
        raise RuntimeError("nenhuma face superior encontrada na tampa")

    aplicar_uv_projecao_topo(tampa, faces_topo, args.top)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    log(f"exportando: {args.output}")
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log("OK — textura do topo projetada nas faces reais")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
