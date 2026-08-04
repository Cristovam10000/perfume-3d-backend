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

# `segment_bottle.py` é irmão deste arquivo; rodando via `blender --python`, o
# diretório do script não entra no sys.path automaticamente.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from segment_bottle import alturas_das_faces, encontrar_corte  # noqa: E402
from top_alignment import estimar_rotacao  # noqa: E402

UP_AXIS = Vector((0.0, 0.0, 1.0))

# Resolucao das mascaras usadas na estimativa de rotacao. Precisa ser suficiente
# para a forma da tampa (triangular, quadrada, circular) sem custar tempo.
_RES_MASCARA = 128


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
    parser.add_argument(
        "--sem-alinhar-rotacao",
        dest="alinhar_rotacao",
        action="store_false",
        help="desliga a estimativa de rotacao por silhueta (util para comparar)",
    )
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
    z_minimo: float | None = None,
) -> list[bpy.types.MeshPolygon]:
    """Faces voltadas para cima, opcionalmente restritas a acima de `z_minimo`.

    Sem `z_minimo` a coleta pega TODA face voltada para cima do frasco — ombro,
    ressaltos do corpo, tudo. Como o Hunyuan entrega um mesh unico, isso fazia a
    projecao ortografica usar a bounding box XY do frasco inteiro e a foto do
    topo saia esticada e deslocada. `z_minimo` vem da segmentacao (o ombro) e
    limita a coleta a tampa.
    """
    matriz = obj.matrix_world

    def elegivel(p: bpy.types.MeshPolygon, t: float) -> bool:
        if normal_mundo(obj, p).dot(UP_AXIS) < t:
            return False
        return z_minimo is None or (matriz @ p.center).z > z_minimo

    faces = [p for p in obj.data.polygons if elegivel(p, threshold)]
    # Fallback progressivo se threshold alto demais
    for t in (0.35, 0.20, 0.0):
        if faces:
            break
        faces = [p for p in obj.data.polygons if elegivel(p, t)]
        if faces and t < threshold:
            log(f"AVISO: threshold relaxado para {t} ({len(faces)} faces)")
    return faces


# ------------------------------------------------------------------ UV + material

def recortar_para_alpha(img_path: Path, destino: Path) -> Path:
    """Recorta a imagem para a bounding box dos pixels opacos.

    A foto do topo vem do BackgroundRemover: o frasco ocupa uma parte do quadro
    e o resto e alpha=0. A projecao ortografica mapeia a imagem INTEIRA (UV 0..1)
    sobre a tampa, entao sem recorte a tampa recebe majoritariamente area
    transparente e o conteudo util sai deslocado e fora de escala.

    Devolve o caminho recortado, ou o original quando nao ha alpha utilizavel.
    """
    import numpy as np

    origem = bpy.data.images.load(str(img_path))
    largura, altura = origem.size
    if largura == 0 or altura == 0:
        return img_path

    px = np.array(origem.pixels[:], dtype=np.float32).reshape(altura, largura, 4)
    opacos = px[:, :, 3] > 0.1
    if not opacos.any():
        log("AVISO: imagem do topo sem pixels opacos — usando original")
        return img_path

    linhas = np.where(opacos.any(axis=1))[0]
    colunas = np.where(opacos.any(axis=0))[0]
    y0, y1 = int(linhas[0]), int(linhas[-1]) + 1
    x0, x1 = int(colunas[0]), int(colunas[-1]) + 1

    if (x1 - x0) < 8 or (y1 - y0) < 8:
        log("AVISO: recorte alpha degenerado — usando original")
        return img_path

    pct = 100.0 * (x1 - x0) * (y1 - y0) / (largura * altura)
    log(
        f"recorte alpha: {largura}x{altura} -> {x1 - x0}x{y1 - y0} "
        f"({pct:.1f}% do quadro original)"
    )

    recorte = px[y0:y1, x0:x1, :]
    nova = bpy.data.images.new(
        "TopTextureCropped", width=x1 - x0, height=y1 - y0, alpha=True
    )
    nova.pixels = recorte.ravel().tolist()
    nova.filepath_raw = str(destino)
    nova.file_format = "PNG"
    nova.save()
    return destino


def mascara_da_malha(
    obj: bpy.types.Object, faces_topo: list[bpy.types.MeshPolygon]
) -> "object":
    """Silhueta da tampa vista de cima, rasterizada numa grade booleana."""
    import numpy as np

    matriz = obj.matrix_world
    verts = obj.data.vertices
    pontos = [
        (matriz @ verts[vi].co)[:2] for face in faces_topo for vi in face.vertices
    ]
    if not pontos:
        return np.zeros((_RES_MASCARA, _RES_MASCARA), dtype=bool)

    arr = np.asarray(pontos, dtype=np.float64)
    minimo, maximo = arr.min(axis=0), arr.max(axis=0)
    span = np.maximum(maximo - minimo, 1e-9)
    idx = ((arr - minimo) / span * (_RES_MASCARA - 1)).astype(np.int32)

    grade = np.zeros((_RES_MASCARA, _RES_MASCARA), dtype=bool)
    grade[idx[:, 1], idx[:, 0]] = True  # linha = Y, coluna = X
    return grade


def mascara_da_foto(img_path: Path) -> "object":
    """Silhueta da foto do topo, a partir do canal alpha."""
    import numpy as np

    imagem = bpy.data.images.load(str(img_path))
    largura, altura = imagem.size
    px = np.array(imagem.pixels[:], dtype=np.float32).reshape(altura, largura, 4)
    opacos = px[:, :, 3] > 0.1

    # Subamostra para a mesma resolucao da grade da malha.
    ys = np.linspace(0, altura - 1, _RES_MASCARA).astype(np.int32)
    xs = np.linspace(0, largura - 1, _RES_MASCARA).astype(np.int32)
    return opacos[np.ix_(ys, xs)]


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
    angulo_graus: float = 0.0,
) -> None:
    """
    Projeta UV ortograficamente nas faces do topo via coordenadas mundo XY.
    Cria material novo e o atribui apenas a essas faces.

    `angulo_graus` gira o sistema de coordenadas da projeção antes de calcular
    a bounding box e os UVs, corrigindo a diferença de orientação entre a foto
    e a malha (ver `top_alignment.py`).
    """
    import math

    mat_world = obj.matrix_world
    verts = obj.data.vertices

    rad = math.radians(angulo_graus)
    cos_a, sen_a = math.cos(rad), math.sin(rad)

    # Coleta todos os vértices das faces do topo em coordenadas mundo
    indices_faces = {p.index for p in faces_topo}
    brutos = []
    for face in faces_topo:
        for vi in face.vertices:
            p = mat_world @ verts[vi].co
            brutos.append((p.x, p.y))

    if not brutos:
        raise RuntimeError("nenhum vértice nas faces do topo")

    # Centro da tampa: a rotação precisa ser em torno dele, não da origem.
    centro_x = sum(x for x, _ in brutos) / len(brutos)
    centro_y = sum(y for _, y in brutos) / len(brutos)

    def girar(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - centro_x, y - centro_y
        return (dx * cos_a - dy * sen_a, dx * sen_a + dy * cos_a)

    girados = [girar(x, y) for x, y in brutos]
    xs = [p[0] for p in girados]
    ys = [p[1] for p in girados]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    log(
        f"bbox XY do topo (rotacao {angulo_graus:.1f}deg): "
        f"x=[{min_x:.3f},{max_x:.3f}] y=[{min_y:.3f},{max_y:.3f}]"
    )

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
                gx, gy = girar(p.x, p.y)
                u = (gx - min_x) / span_x
                v = (gy - min_y) / span_y
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

    # Sem segmentacao, `identificar_tampa` devolve o frasco inteiro (o Hunyuan
    # entrega mesh unico) e a projecao se espalha pelo corpo. O corte no ombro
    # restringe a coleta e, por consequencia, a bounding box da projecao.
    z_corte, diag = encontrar_corte(alturas_das_faces(tampa))
    if z_corte is None:
        log(f"AVISO: ombro nao identificado ({diag.get('motivo')}) — projetando sem recorte")
    else:
        log(
            f"ombro em z_rel={diag['z_rel_pico']:.2f} (razao {diag['razao']:.2f}x); "
            f"limitando projecao a z > {z_corte:.4f}"
        )

    faces_topo = coletar_faces_topo(tampa, args.cosine_threshold, z_minimo=z_corte)
    log(f"faces do topo: {len(faces_topo)}")

    imagem_topo = recortar_para_alpha(
        args.top, args.output.parent / f"{args.output.stem}_top_crop.png"
    )

    # Estimativa de rotacao pela silhueta. `permitir_espelho` fica desligado:
    # a projecao ortografica e a foto de cima tem a mesma lateralidade, e num
    # frasco quase simetrico o espelho seria escolhido por ruido, produzindo um
    # logo invertido — pior do que um logo girado.
    angulo = 0.0
    if args.alinhar_rotacao:
        estimativa = estimar_rotacao(
            mascara_da_malha(tampa, faces_topo),
            mascara_da_foto(imagem_topo),
            permitir_espelho=False,
        )
        if estimativa is None:
            log("AVISO: mascaras insuficientes para estimar rotacao — usando 0deg")
        elif not estimativa.confiavel:
            log(
                f"rotacao ambigua (IoU={estimativa.iou:.3f}, "
                f"confianca={estimativa.confianca:.3f}) — tampa provavelmente "
                "circular; nao aplicando rotacao"
            )
        else:
            angulo = estimativa.angulo_graus
            log(
                f"rotacao estimada: {angulo:.1f}deg "
                f"(IoU={estimativa.iou:.3f}, confianca={estimativa.confianca:.3f})"
            )

    if not faces_topo:
        raise RuntimeError("nenhuma face superior encontrada na tampa")

    aplicar_uv_projecao_topo(tampa, faces_topo, imagem_topo, angulo_graus=angulo)

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
