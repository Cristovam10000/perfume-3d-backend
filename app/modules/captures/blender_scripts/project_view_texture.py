"""Projeta uma foto real do frasco nas faces que a foto enxerga.

Em vez de criar um plano flutuante (decal), modifica o material daquelas faces
para exibir a imagem via projecao ortografica ao longo de um eixo.

Dois eixos hoje:

- `z_pos` (**topo**) — o Hunyuan nao reconstroi a tampa, porque nenhuma das 4
  vistas cardeais a enxerga; ela sai como um disco liso.
- `y_pos` (**costas**) — o Hunyuan gera a *geometria* com 4 vistas mas a
  *textura* com UMA. O pipeline de paint (`tencent/Hunyuan3D-2`) aceita uma
  unica imagem de referencia e **sintetiza** as demais vistas a partir dela, de
  modo que o verso do frasco sai inventado. Nos temos a foto real do verso; a
  projecao troca o palpite pelo pixel medido.

Fluxo:
1. Importa o GLB.
2. Identifica o mesh de maior Z (o frasco; o Hunyuan entrega bloco unico).
3. Coleta as faces cuja normal aponta para o eixo (dot(n, eixo) >= threshold),
   restritas a faixa de altura correspondente (tampa acima do ombro, corpo
   abaixo).
4. Calcula UV por projecao ortografica: descarta a coordenada do eixo de
   projecao e normaliza as duas restantes para 0..1.
5. Cria um UV map proprio e um material com a imagem, atribuidos so aquelas
   faces.
6. Exporta GLB com a textura embutida.

Roda dentro do Blender headless:

    blender.exe --background --python project_view_texture.py -- \\
        --input  path/to/refined.glb \\
        --photo  path/to/05_top_segmented.png \\
        --output path/to/with_top.glb \\
        --axis   z_pos \\
        [--cosine-threshold 0.45]
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

# Eixos de projecao suportados. Para cada um:
#   vetor      — direcao para onde as faces alvo apontam, em coordenadas mundo.
#   uv         — indices das coordenadas de mundo que viram (u, v).
#   inverter_u — espelha o u.
#   faixa      — recorte em Z: "acima" do ombro, "abaixo" dele, ou "tudo".
#
# A regra da faixa e uma so: **a extensao da foto tem que casar com a extensao
# das faces alvo**, porque a projecao estica a imagem inteira sobre elas.
#   - topo:   a foto mostra so a tampa      -> faces so acima do ombro.
#   - costas: a foto mostra o frasco inteiro -> todas as faces traseiras.
# Restringir as costas ao corpo desalinha a imagem: a tampa da foto cai sobre a
# parte de cima do corpo e o relevo escorrega para baixo (medido em 03/08).
#
# Sobre `inverter_u` em `y_pos`: olhando o frasco de tras para a frente, o +X do
# mundo aparece a ESQUERDA do observador — igual a olhar alguem de costas, cuja
# mao direita esta do seu lado esquerdo. Sem a inversao as costas saem
# espelhadas (texto de composicao ao contrario).
#
# A convencao "frente = -Y" vem de FRONT_AXES em project_label.py, logo o verso
# do frasco e +Y.
EIXOS = {
    "z_pos": {
        "vetor": Vector((0.0, 0.0, 1.0)),
        "uv": (0, 1),          # (x, y)
        "inverter_u": False,
        "faixa": "acima",      # tampa
        "rotulo": "topo",
        "uv_layer": "TopProjectionUV",
        "material": "TopTextureMaterial",
    },
    "y_pos": {
        "vetor": Vector((0.0, 1.0, 0.0)),
        "uv": (0, 2),          # (x, z)
        "inverter_u": True,
        "faixa": "tudo",       # frasco inteiro visto de tras
        "rotulo": "costas",
        "uv_layer": "BackProjectionUV",
        "material": "BackTextureMaterial",
    },
}

# Resolucao das mascaras usadas na estimativa de rotacao. Precisa ser suficiente
# para a forma da tampa (triangular, quadrada, circular) sem custar tempo.
_RES_MASCARA = 128


def log(msg: str) -> None:
    print(f"[project-view] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="project_view_texture")
    parser.add_argument("--input",  required=True, type=Path)
    parser.add_argument("--photo",  required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--axis", choices=sorted(EIXOS), default="z_pos")
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


def coletar_faces_por_normal(
    obj: bpy.types.Object,
    eixo: Vector,
    threshold: float,
    z_corte: float | None = None,
    faixa: str = "acima",
) -> list[bpy.types.MeshPolygon]:
    """Faces cuja normal aponta para `eixo`, restritas a uma faixa de altura.

    `z_corte` vem da segmentacao (o ombro) e serve para casar a extensao das
    faces com a extensao da foto:

    - `faixa="acima"` (topo): so a tampa. A foto do topo mostra so a tampa; sem
      o corte, a coleta pegaria ombro e ressaltos do corpo, a bounding box da
      projecao viraria a do frasco inteiro e a foto sairia esticada.
    - `faixa="tudo"` (costas): a foto do verso mostra o frasco inteiro, entao o
      alvo tambem tem que ser o frasco inteiro.
    """
    matriz = obj.matrix_world

    def na_faixa(p: bpy.types.MeshPolygon) -> bool:
        if z_corte is None or faixa == "tudo":
            return True
        z = (matriz @ p.center).z
        return z > z_corte if faixa == "acima" else z <= z_corte

    def elegivel(p: bpy.types.MeshPolygon, t: float) -> bool:
        return normal_mundo(obj, p).dot(eixo) >= t and na_faixa(p)

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
    obj: bpy.types.Object,
    faces: list[bpy.types.MeshPolygon],
    uv_idx: tuple[int, int] = (0, 1),
) -> "object":
    """Silhueta das faces vista ao longo do eixo, numa grade booleana."""
    import numpy as np

    matriz = obj.matrix_world
    verts = obj.data.vertices
    iu, iv = uv_idx
    pontos = [
        ((matriz @ verts[vi].co)[iu], (matriz @ verts[vi].co)[iv])
        for face in faces
        for vi in face.vertices
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


def criar_material_projecao(
    img_path: Path, nome: str, uv_layer: str
) -> bpy.types.Material:
    """Cria material com Image Texture RGBA (transparencia preservada).

    `uv_layer` entra num no UV Map explicito. Sem ele a textura amostra o UV
    **ativo** da malha, e como topo e costas convivem no mesmo mesh com UV maps
    diferentes, a segunda projecao a rodar roubaria o UV da primeira.
    """
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
    no_uv = nodes.new("ShaderNodeUVMap")
    no_uv.location = (-420, 80)
    no_uv.uv_map = uv_layer

    # Conecta: UV explicito → textura → BSDF (cor) + alpha → Mix (transparencia)
    links.new(no_uv.outputs["UV"], tex.inputs["Vector"])
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


def aplicar_uv_projecao(
    obj: bpy.types.Object,
    faces_alvo: list[bpy.types.MeshPolygon],
    img_path: Path,
    eixo: dict,
    angulo_graus: float = 0.0,
) -> None:
    """
    Projeta UV ortograficamente nas faces alvo, descartando a coordenada do
    eixo de projecao. Cria material novo e o atribui apenas a essas faces.

    `angulo_graus` gira o sistema de coordenadas da projeção antes de calcular
    a bounding box e os UVs, corrigindo a diferença de orientação entre a foto
    e a malha (ver `top_alignment.py`). So o topo usa isso; nas costas a
    orientacao ja esta fixada pelo proprio eixo.
    """
    import math

    mat_world = obj.matrix_world
    verts = obj.data.vertices
    iu, iv = eixo["uv"]
    sinal_u = -1.0 if eixo["inverter_u"] else 1.0

    rad = math.radians(angulo_graus)
    cos_a, sen_a = math.cos(rad), math.sin(rad)

    def plano(vi: int) -> tuple[float, float]:
        """Coordenada mundo do vertice reduzida ao plano da projecao."""
        p = mat_world @ verts[vi].co
        return (p[iu] * sinal_u, p[iv])

    # Coleta todos os vértices das faces alvo no plano da projecao
    indices_faces = {p.index for p in faces_alvo}
    brutos = [plano(vi) for face in faces_alvo for vi in face.vertices]

    if not brutos:
        raise RuntimeError("nenhum vértice nas faces alvo")

    # Centro das faces: a rotação precisa ser em torno dele, não da origem.
    centro_a = sum(a for a, _ in brutos) / len(brutos)
    centro_b = sum(b for _, b in brutos) / len(brutos)

    def girar(a: float, b: float) -> tuple[float, float]:
        da, db = a - centro_a, b - centro_b
        return (da * cos_a - db * sen_a, da * sen_a + db * cos_a)

    girados = [girar(a, b) for a, b in brutos]
    us = [p[0] for p in girados]
    vs = [p[1] for p in girados]

    min_u, max_u = min(us), max(us)
    min_v, max_v = min(vs), max(vs)
    span_u = max(max_u - min_u, 1e-6)
    span_v = max(max_v - min_v, 1e-6)
    log(
        f"bbox da projecao {eixo['rotulo']} (rotacao {angulo_graus:.1f}deg): "
        f"u=[{min_u:.3f},{max_u:.3f}] v=[{min_v:.3f},{max_v:.3f}]"
    )

    # Cria ou substitui o UV map desta projecao
    uv_nome = eixo["uv_layer"]
    if uv_nome in obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[uv_nome])
    uv_layer = obj.data.uv_layers.new(name=uv_nome)
    obj.data.uv_layers.active = uv_layer

    # Preenche UVs: faces alvo recebem a projecao; restantes ficam em (0,0)
    for face in obj.data.polygons:
        if face.index in indices_faces:
            for loop_i, vi in zip(face.loop_indices, face.vertices):
                ga, gb = girar(*plano(vi))
                uv_layer.data[loop_i].uv = (
                    (ga - min_u) / span_u,
                    (gb - min_v) / span_v,
                )
        else:
            for loop_i in face.loop_indices:
                uv_layer.data[loop_i].uv = (0.0, 0.0)

    # Adiciona material novo ao objeto
    material = criar_material_projecao(img_path, eixo["material"], uv_nome)
    obj.data.materials.append(material)
    mat_idx = len(obj.data.materials) - 1

    # Atribui material apenas às faces alvo
    for face in obj.data.polygons:
        if face.index in indices_faces:
            face.material_index = mat_idx

    # Faz o UV map ativo usar o material correto
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            node.extension = "CLIP"

    log(f"UV projecao aplicada: {len(faces_alvo)} faces, material_index={mat_idx}")


# ------------------------------------------------------------------ main

def main() -> int:
    args = parse_args()
    eixo = EIXOS[args.axis]
    log(f"input             = {args.input}")
    log(f"photo             = {args.photo}")
    log(f"output            = {args.output}")
    log(f"axis              = {args.axis} ({eixo['rotulo']})")
    log(f"cosine-threshold  = {args.cosine_threshold}")

    if not args.input.exists():
        raise FileNotFoundError(f"GLB nao encontrado: {args.input}")
    if not args.photo.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {args.photo}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("GLB sem meshes")
    log(f"meshes: {[o.name for o in meshes]}")

    frasco = identificar_tampa(meshes)
    if frasco is None:
        raise RuntimeError("mesh do frasco nao identificado")
    log(f"mesh: '{frasco.name}' (max_z={max_z_bbox(frasco):.4f})")

    # O Hunyuan entrega mesh unico, sem distincao entre corpo e tampa. Sem o
    # corte no ombro a coleta pega faces dos dois e a bounding box da projecao
    # vira a do frasco inteiro — a foto sai esticada e deslocada.
    z_corte, diag = encontrar_corte(alturas_das_faces(frasco))
    if z_corte is None:
        log(f"AVISO: ombro nao identificado ({diag.get('motivo')}) — projetando sem recorte")
    else:
        comparador = ">" if eixo["faixa"] == "acima" else "<="
        log(
            f"ombro em z_rel={diag['z_rel_pico']:.2f} (razao {diag['razao']:.2f}x); "
            f"limitando projecao a z {comparador} {z_corte:.4f}"
        )

    faces_alvo = coletar_faces_por_normal(
        frasco,
        eixo["vetor"],
        args.cosine_threshold,
        z_corte=z_corte,
        faixa=eixo["faixa"],
    )
    log(f"faces alvo ({eixo['rotulo']}): {len(faces_alvo)}")
    if not faces_alvo:
        raise RuntimeError(f"nenhuma face voltada para {args.axis} encontrada")

    imagem = recortar_para_alpha(
        args.photo, args.output.parent / f"{args.output.stem}_{args.axis}_crop.png"
    )

    # Estimativa de rotacao pela silhueta — so no topo. `permitir_espelho` fica
    # desligado: a projecao ortografica e a foto de cima tem a mesma
    # lateralidade, e num frasco quase simetrico o espelho seria escolhido por
    # ruido, produzindo um logo invertido — pior do que um logo girado.
    #
    # Nas costas nao ha o que estimar: o eixo ja fixa a orientacao, e girar a
    # projecao no plano XZ inclinaria o frasco.
    angulo = 0.0
    if args.alinhar_rotacao and args.axis == "z_pos":
        estimativa = estimar_rotacao(
            mascara_da_malha(frasco, faces_alvo, eixo["uv"]),
            mascara_da_foto(imagem),
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

    aplicar_uv_projecao(frasco, faces_alvo, imagem, eixo, angulo_graus=angulo)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    log(f"exportando: {args.output}")
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log(f"OK — textura de {eixo['rotulo']} projetada nas faces reais")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
