"""Projeta a label real extraida da foto na face frontal do GLB.

Roda dentro do Blender headless. O script nao importa nada do backend.

Fluxo:
1. Importa o GLB.
2. Escolhe o corpo do frasco por maior area (preferindo material sem textura).
3. Detecta o cluster frontal pela normal alinhada ao eixo de frente.
4. Cria um plano/decal com `LabelMaterial` e UV 0..1 usando a imagem da label.
5. Exporta GLB com a label embutida.

O uso de decal e intencional: GLBs do Hunyuan frequentemente chegam com um
unico material texturizado e geometria fragmentada. Um decal preserva o mesh
original e evita destruir a textura existente enquanto torna a label legivel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

# `segment_bottle.py` é irmão deste arquivo; rodando via `blender --python`, o
# diretório do script não entra no sys.path automaticamente.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from segment_bottle import alturas_das_faces, encontrar_corte  # noqa: E402


FRONT_AXES = {
    "front_y_neg": Vector((0.0, -1.0, 0.0)),
    "front_y_pos": Vector((0.0, 1.0, 0.0)),
    "front_x_neg": Vector((-1.0, 0.0, 0.0)),
    "front_x_pos": Vector((1.0, 0.0, 0.0)),
    "front_z_neg": Vector((0.0, 0.0, -1.0)),
    "front_z_pos": Vector((0.0, 0.0, 1.0)),
}


def log(msg: str) -> None:
    print(f"[project-label] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="project_label")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--label", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--front-axis", choices=sorted(FRONT_AXES), default="front_y_neg")
    parser.add_argument("--cosine-threshold", type=float, default=0.70)
    parser.add_argument("--label-scale", type=float, default=0.70)
    parser.add_argument(
        "--vertical-position",
        type=float,
        default=None,
        help=(
            "Altura do centro da label na silhueta do frasco (0=topo, 1=base), "
            "vinda do LabelExtractor. Sem isso o decal cai no centroide do "
            "corpo, que fica abaixo da label real na maioria dos frascos."
        ),
    )
    return parser.parse_args(get_argv_after_double_dash())


def area_poligono_mundo(obj: bpy.types.Object, poligono: bpy.types.MeshPolygon) -> float:
    vertices = obj.data.vertices
    matriz = obj.matrix_world
    indices = list(poligono.vertices)
    if len(indices) < 3:
        return 0.0

    origem = matriz @ vertices[indices[0]].co
    area = 0.0
    for indice in range(1, len(indices) - 1):
        ponto_b = matriz @ vertices[indices[indice]].co
        ponto_c = matriz @ vertices[indices[indice + 1]].co
        area += ((ponto_b - origem).cross(ponto_c - origem)).length * 0.5
    return area


def calcular_area_mesh(obj: bpy.types.Object) -> float:
    if not obj.data:
        return 0.0
    return sum(area_poligono_mundo(obj, poligono) for poligono in obj.data.polygons)


def centro_poligono_mundo(obj: bpy.types.Object, poligono: bpy.types.MeshPolygon) -> Vector:
    matriz = obj.matrix_world
    vertices = obj.data.vertices
    pontos = [matriz @ vertices[indice].co for indice in poligono.vertices]
    if not pontos:
        return matriz @ poligono.center
    centro = Vector((0.0, 0.0, 0.0))
    for ponto in pontos:
        centro += ponto
    return centro / len(pontos)


def normal_poligono_mundo(obj: bpy.types.Object, poligono: bpy.types.MeshPolygon) -> Vector:
    matriz_normal = obj.matrix_world.to_3x3().inverted().transposed()
    normal = matriz_normal @ poligono.normal
    if normal.length == 0:
        return Vector((0.0, 0.0, 1.0))
    return normal.normalized()


def material_tem_textura_image(mat: bpy.types.Material | None) -> bool:
    if not mat or not mat.use_nodes:
        return False
    for no in mat.node_tree.nodes:
        if no.type != "BSDF_PRINCIPLED":
            continue
        entrada_cor = no.inputs.get("Base Color")
        if entrada_cor is None or not entrada_cor.links:
            continue
        for link in entrada_cor.links:
            origem = link.from_node
            if origem.type == "TEX_IMAGE" or origem.bl_idname == "ShaderNodeTexImage":
                return True
    return False


def identificar_corpo(meshes: list[bpy.types.Object]) -> bpy.types.Object | None:
    """Escolhe o corpo: maior area, preferindo material sem textura."""
    candidatos_sem_textura = []
    todos = []
    for obj in meshes:
        area = calcular_area_mesh(obj)
        if area <= 0:
            continue
        todos.append((area, obj))
        mat = obj.data.materials[0] if obj.data.materials else None
        if not material_tem_textura_image(mat):
            candidatos_sem_textura.append((area, obj))

    candidatos = candidatos_sem_textura or todos
    if not candidatos:
        return None
    candidatos.sort(key=lambda item: item[0], reverse=True)
    return candidatos[0][1]


def detectar_cluster_frontal(
    obj: bpy.types.Object,
    eixo_frente: Vector,
    *,
    threshold_inicial: float,
    z_maximo: float | None = None,
) -> tuple[list[bpy.types.MeshPolygon], float, int]:
    """Retorna poligonos frontais, area total e face principal.

    `z_maximo` restringe o cluster ao **corpo** do frasco (abaixo do ombro).
    Sem ele, "voltado para a frente" inclui tampa e adereços — no La vivacité o
    laço lateral puxava o centroide ponderado por área para a esquerda e a
    `altura_face` dava 1,88 num frasco de altura 1,9, ou seja, o cluster era o
    frasco inteiro. O decal saía pequeno e deslocado para a borda.
    """
    area_total = sum(area_poligono_mundo(obj, p) for p in obj.data.polygons)
    if area_total <= 0:
        raise RuntimeError("mesh sem area")

    matriz = obj.matrix_world

    def no_corpo(poligono: bpy.types.MeshPolygon) -> bool:
        return z_maximo is None or (matriz @ poligono.center).z <= z_maximo

    melhor: tuple[list[bpy.types.MeshPolygon], float, int] | None = None
    for threshold in (threshold_inicial, 0.55, 0.40, 0.25):
        candidatos = []
        area_cluster = 0.0
        maior_area = 0.0
        face_indice = -1

        for poligono in obj.data.polygons:
            if not no_corpo(poligono):
                continue
            normal = normal_poligono_mundo(obj, poligono)
            if normal.dot(eixo_frente) < threshold:
                continue
            area = area_poligono_mundo(obj, poligono)
            candidatos.append(poligono)
            area_cluster += area
            if area > maior_area:
                maior_area = area
                face_indice = poligono.index

        if candidatos and area_cluster / area_total >= 0.05:
            return candidatos, area_cluster, face_indice
        if melhor is None or area_cluster > melhor[1]:
            melhor = (candidatos, area_cluster, face_indice)

    if melhor is None or not melhor[0] or melhor[1] / area_total < 0.01:
        raise RuntimeError("frontal face not found, mesh may be too irregular")
    log("AVISO: cluster frontal pequeno; usando melhor fallback encontrado")
    return melhor


def criar_basis(normal: Vector) -> tuple[Vector, Vector, Vector]:
    normal_media = normal.normalized() if normal.length else Vector((0.0, -1.0, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    if abs(normal_media.dot(up)) > 0.95:
        up = Vector((1.0, 0.0, 0.0))
    eixo_u = up.cross(normal_media)
    if eixo_u.length == 0:
        eixo_u = Vector((1.0, 0.0, 0.0))
    eixo_u.normalize()
    eixo_v = normal_media.cross(eixo_u)
    if eixo_v.length == 0:
        eixo_v = Vector((0.0, 0.0, 1.0))
    eixo_v.normalize()
    return eixo_u, eixo_v, normal_media


def criar_material_label(label_path: Path) -> bpy.types.Material:
    """Cria ou substitui LabelMaterial com Image Texture."""
    for mat in list(bpy.data.materials):
        if mat.name.split(".")[0] == "LabelMaterial":
            bpy.data.materials.remove(mat)

    imagem = bpy.data.images.load(str(label_path))
    try:
        imagem.pack()
    except RuntimeError:
        pass

    mat = bpy.data.materials.new("LabelMaterial")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    saida = nodes.new(type="ShaderNodeOutputMaterial")
    saida.location = (420, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (180, 0)
    tex = nodes.new(type="ShaderNodeTexImage")
    tex.location = (-120, 40)
    tex.image = imagem
    try:
        tex.extension = "CLIP"
    except TypeError:
        pass

    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs["BSDF"], saida.inputs["Surface"])

    try:
        mat.surface_render_method = "BLENDED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass

    return mat


def dimensoes_label(label_path: Path) -> tuple[int, int, float]:
    imagem = bpy.data.images.load(str(label_path), check_existing=True)
    largura, altura = int(imagem.size[0]), int(imagem.size[1])
    if largura <= 0 or altura <= 0:
        raise RuntimeError("imagem de label invalida")
    return largura, altura, largura / altura


def criar_decal_label(
    obj: bpy.types.Object,
    poligonos: list[bpy.types.MeshPolygon],
    eixo_frente: Vector,
    label_path: Path,
    *,
    label_scale: float,
    posicao_vertical: float | None = None,
) -> float:
    """Cria um plano com a label sobre o cluster frontal.

    `posicao_vertical` (0=topo do frasco, 1=base) vem do `LabelExtractor` e
    define a altura do decal. Sem ela o decal fica no centroide do cluster —
    o meio do corpo —, tipicamente abaixo de onde a label realmente está.
    """
    largura_img, altura_img, aspecto_label = dimensoes_label(label_path)
    log(f"label image = {largura_img}x{altura_img} (aspect={aspecto_label:.3f})")

    normal_soma = Vector((0.0, 0.0, 0.0))
    area_soma = 0.0
    centros = []
    for poligono in poligonos:
        area = area_poligono_mundo(obj, poligono)
        normal_soma += normal_poligono_mundo(obj, poligono) * max(area, 1e-9)
        area_soma += area
        centros.append((centro_poligono_mundo(obj, poligono), area))

    normal_media = normal_soma.normalized() if normal_soma.length else eixo_frente
    eixo_u, eixo_v, normal_media = criar_basis(normal_media)

    coords_u = []
    coords_v = []
    for poligono in poligonos:
        for indice in poligono.vertices:
            ponto = obj.matrix_world @ obj.data.vertices[indice].co
            coords_u.append(ponto.dot(eixo_u))
            coords_v.append(ponto.dot(eixo_v))

    min_u, max_u = min(coords_u), max(coords_u)
    min_v, max_v = min(coords_v), max(coords_v)
    largura_face = max(max_u - min_u, 1e-6)
    altura_face = max(max_v - min_v, 1e-6)
    aspecto_face = largura_face / altura_face
    diferenca_aspecto = max(aspecto_label / aspecto_face, aspecto_face / aspecto_label)
    if diferenca_aspecto > 3.0:
        log(
            "AVISO: aspect ratio da label difere bastante da face "
            f"(label={aspecto_label:.2f}, face={aspecto_face:.2f})"
        )

    max_largura = largura_face * label_scale
    max_altura = altura_face * label_scale
    if max_largura / max_altura > aspecto_label:
        altura_label = max_altura
        largura_label = altura_label * aspecto_label
    else:
        largura_label = max_largura
        altura_label = largura_label / aspecto_label

    centro_3d = Vector((0.0, 0.0, 0.0))
    peso_total = 0.0
    for centro, area in centros:
        peso = max(area, 1e-9)
        centro_3d += centro * peso
        peso_total += peso
    centro_3d = centro_3d / max(peso_total, 1e-9)

    if posicao_vertical is not None:
        # Converte "fração a partir do topo da silhueta" para Z do mundo,
        # usando a extensão vertical do frasco INTEIRO — a mesma referência que
        # o extrator usou na foto (a silhueta inclui a tampa).
        zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
        z_topo, z_base = max(zs), min(zs)
        alvo = z_topo - posicao_vertical * (z_topo - z_base)
        log(
            f"altura da label: {posicao_vertical:.2f} da silhueta -> "
            f"z={alvo:.4f} (centroide era {centro_3d.z:.4f})"
        )
        centro_3d = Vector((centro_3d.x, centro_3d.y, alvo))

    # O decal e um plano PLANO sobre uma superficie CURVA. Um offset fixo deixa
    # o meio do plano atras da barriga do frasco, e o decal aparece partido em
    # manchas nas laterais. Projeta-se os vertices do cluster no eixo da normal
    # e coloca-se o plano a frente do ponto mais saliente.
    profundidades = [
        (obj.matrix_world @ obj.data.vertices[indice].co).dot(normal_media)
        for poligono in poligonos
        for indice in poligono.vertices
    ]
    diagonal = max(obj.dimensions.length, 1.0)
    margem = diagonal * 0.004
    if profundidades:
        saliencia = max(profundidades) - centro_3d.dot(normal_media)
        avanco = max(saliencia, 0.0) + margem
    else:
        avanco = margem
    centro_3d = centro_3d + normal_media * avanco
    log(f"decal avancado {avanco:.4f} a frente do centroide (barriga + margem)")

    metade_u = eixo_u * (largura_label / 2.0)
    metade_v = eixo_v * (altura_label / 2.0)
    vertices = [
        centro_3d - metade_u - metade_v,
        centro_3d + metade_u - metade_v,
        centro_3d + metade_u + metade_v,
        centro_3d - metade_u + metade_v,
    ]

    malha = bpy.data.meshes.new("ProjectedLabelMesh")
    malha.from_pydata([tuple(v) for v in vertices], [], [(0, 1, 2, 3)])
    malha.update()
    decal = bpy.data.objects.new("ProjectedLabel", malha)
    bpy.context.collection.objects.link(decal)

    material = criar_material_label(label_path)
    decal.data.materials.append(material)
    decal.data.polygons[0].material_index = 0

    uv_layer = decal.data.uv_layers.new(name="LabelUV")
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for loop_index, uv in zip(decal.data.polygons[0].loop_indices, uvs):
        uv_layer.data[loop_index].uv = uv

    cobertura = min(1.0, (largura_label * altura_label) / (largura_face * altura_face))
    log(
        f"decal criado: largura={largura_label:.4f}, altura={altura_label:.4f}, "
        f"coverage={cobertura:.3f}"
    )
    return cobertura


def main() -> int:
    args = parse_args()
    log(f"input      = {args.input}")
    log(f"label      = {args.label}")
    log(f"output     = {args.output}")
    log(f"front-axis = {args.front_axis}")

    if not args.input.exists():
        raise FileNotFoundError(f"GLB de entrada nao encontrado: {args.input}")
    if not args.label.exists():
        raise FileNotFoundError(f"Label nao encontrada: {args.label}")
    if not 0.0 < args.label_scale <= 1.0:
        raise ValueError("--label-scale deve estar em (0, 1]")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))

    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("GLB sem meshes")
    log(f"meshes encontrados: {[obj.name for obj in meshes]}")

    corpo = identificar_corpo(meshes)
    if corpo is None:
        raise RuntimeError("corpo do frasco nao identificado")
    log(f"corpo identificado: {corpo.name}")

    # Restringe ao corpo: sem isso a tampa e adereços (o laço do La vivacité)
    # entram no cluster frontal e deslocam o decal.
    z_corte, diag = encontrar_corte(alturas_das_faces(corpo))
    if z_corte is None:
        log(f"AVISO: ombro nao identificado ({diag.get('motivo')}) — usando o mesh inteiro")
    else:
        log(
            f"ombro em z_rel={diag['z_rel_pico']:.2f} (razao {diag['razao']:.2f}x); "
            f"cluster frontal limitado a z <= {z_corte:.4f}"
        )

    eixo_frente = FRONT_AXES[args.front_axis].normalized()
    poligonos, area_cluster, face_indice = detectar_cluster_frontal(
        corpo,
        eixo_frente,
        threshold_inicial=args.cosine_threshold,
        z_maximo=z_corte,
    )
    log(
        f"cluster frontal: faces={len(poligonos)}, area={area_cluster:.4f}, "
        f"target_face_index={face_indice}"
    )

    cobertura = criar_decal_label(
        corpo,
        poligonos,
        eixo_frente,
        args.label,
        label_scale=args.label_scale,
        posicao_vertical=args.vertical_position,
    )

    log(f"STATS:target_face_index={face_indice},coverage_ratio={cobertura:.4f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Exportando: {args.output}")
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log("OK - label projetada")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
