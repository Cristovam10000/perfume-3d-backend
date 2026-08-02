"""Refina um GLB gerado por IA (Hunyuan3D) aplicando vidro PBR no corpo.

A IA produz um GLB onde o "vidro" do frasco vira um material opaco
azulado (a IA pinta a refração do ambiente como textura). O modo de
refinamento é controlado por `--body-mode`:

- `auto`  (legado): aplica vidro apenas se existir mesh SEM Image Texture
  no Base Color (caso de GLBs de template ou Hunyuan sem paint). Saídas
  reais do Hunyuan com paint vêm 100% texturizadas, então `auto` vira
  no-op nelas.
- `glass`: frasco classificado como transparente. Se não houver corpo sem
  textura, aplica transmissão PBR ao maior mesh texturizado PRESERVANDO a
  textura no Base Color (vira tinte do vidro). A label real é reprojetada
  pelo stage seguinte, então alterar o material do corpo é seguro.
- `keep`: frasco classificado como opaco. Materiais do corpo ficam
  intactos (a textura pintada pela IA é o resultado correto).

Em todos os modos: opcionalmente aplica cor no líquido se mesh "Liquid"
ou material "water" estiver presente.

Roda dentro do Blender em modo headless:

    blender.exe --background --python refine_ai_mesh.py -- \\
        --input  path/to/raw.glb \\
        --output path/to/refined.glb \\
        [--body-mode auto|glass|keep] \\
        [--liquid-color #RRGGBB]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)
from mathutils import Vector  # noqa: E402

# `segment_bottle.py` é irmão deste arquivo. Rodando via `blender --python`, o
# diretório do script não entra no sys.path automaticamente.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from segment_bottle import (  # noqa: E402
    MATERIAL_CORPO,
    alturas_das_faces,
    encontrar_corte,
    garantir_dois_materiais,
)


# === Constantes do shader de vidro (calibradas para perfume) ===
GLASS_PARAMS = {
    "base_color": (1.0, 1.0, 1.0, 1.0),  # vidro transparente sem tinte
    "roughness": 0.05,                    # vidro polido; >0.1 = fosco
    "ior": 1.45,                          # boro-silicato típico de perfumaria
    "transmission": 1.0,                  # transmissão total
    "alpha": 0.3,                         # semi-visível no preview
}

CAP_METALLIC_PARAMS = {
    "base_color": (0.04, 0.04, 0.05, 1.0),  # preto levemente azulado
    "roughness": 0.18,
    "metallic": 0.3,
}


# --------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[refine] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    """Blender passa nossos args depois de '--'. Antes disso são args do Blender."""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def parse_color_hex(value: str) -> tuple[float, float, float, float]:
    """Aceita '#RRGGBB' ou 'RRGGBB' e devolve (r, g, b, a) em [0,1]."""
    raw = value.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"cor hex deve ter 6 dígitos: '{value}'")
    r = int(raw[0:2], 16) / 255.0
    g = int(raw[2:4], 16) / 255.0
    b = int(raw[4:6], 16) / 255.0
    return (r, g, b, 1.0)


def nome_base_blender(nome: str) -> str:
    """Remove sufixos automáticos do Blender, como '.001', e normaliza."""
    return nome.split(".")[0].lower()


# --------------------------------------------------------------------- análise

def calcular_area_mesh(obj: bpy.types.Object) -> float:
    """Soma das áreas de todas as faces em coordenadas mundo."""
    if not obj.data or not obj.data.polygons:
        return 0.0

    vertices = obj.data.vertices
    matriz_mundo = obj.matrix_world
    area_total = 0.0

    for poligono in obj.data.polygons:
        indices = list(poligono.vertices)
        if len(indices) < 3:
            continue

        origem = matriz_mundo @ vertices[indices[0]].co
        for indice in range(1, len(indices) - 1):
            ponto_b = matriz_mundo @ vertices[indices[indice]].co
            ponto_c = matriz_mundo @ vertices[indices[indice + 1]].co
            area_total += ((ponto_b - origem).cross(ponto_c - origem)).length * 0.5

    return area_total


def material_tem_textura_image(mat: bpy.types.Material) -> bool:
    """True se o Base Color do Principled BSDF está ligado a uma Image Texture."""
    if not mat or not mat.use_nodes:
        return False
    for no in mat.node_tree.nodes:
        if no.type != "BSDF_PRINCIPLED":
            continue
        entrada_cor = no.inputs.get("Base Color")
        if entrada_cor is None or not entrada_cor.links:
            continue
        for link in entrada_cor.links:
            no_origem = link.from_node
            if no_origem.type == "TEX_IMAGE" or no_origem.bl_idname == "ShaderNodeTexImage":
                return True
    return False


def identificar_corpo_texturizado(
    meshes: list[bpy.types.Object],
) -> tuple[bpy.types.Object | None, bpy.types.Material | None]:
    """Retorna (obj, material) do maior mesh COM material, texturizado ou não.

    Usado no modo `glass` quando a saída do Hunyuan vem 100% texturizada
    (caso normal com paint pipeline): o maior mesh é o frasco inteiro e o
    material texturizado recebe transmissão preservando a textura.
    """
    candidatos: list[tuple[float, bpy.types.Object, bpy.types.Material]] = []
    for obj in meshes:
        if not obj.data.materials:
            continue
        mat = obj.data.materials[0]
        if mat is None:
            continue
        area = calcular_area_mesh(obj)
        candidatos.append((area, obj, mat))

    if not candidatos:
        return None, None

    candidatos.sort(key=lambda t: t[0], reverse=True)
    _, obj_corpo, mat_corpo = candidatos[0]
    return obj_corpo, mat_corpo


def identificar_corpo_vidro(
    meshes: list[bpy.types.Object],
) -> tuple[bpy.types.Object | None, bpy.types.Material | None]:
    """Retorna (obj, material) do maior mesh sem Image Texture no Base Color.

    Prioridade: maior área de superfície entre candidatos sem textura.
    Se todos os materiais tiverem textura (ex: GLB totalmente texturizado),
    retorna (None, None) e o script exporta o GLB sem alterações.
    """
    candidatos: list[tuple[float, bpy.types.Object, bpy.types.Material]] = []
    for obj in meshes:
        if not obj.data.materials:
            continue
        mat = obj.data.materials[0]
        if mat is None:
            continue
        if material_tem_textura_image(mat):
            continue
        area = calcular_area_mesh(obj)
        candidatos.append((area, obj, mat))

    if not candidatos:
        return None, None

    candidatos.sort(key=lambda t: t[0], reverse=True)
    _, obj_corpo, mat_corpo = candidatos[0]
    return obj_corpo, mat_corpo


def segmentar_corpo(obj: bpy.types.Object) -> bpy.types.Material | None:
    """Separa corpo e tampa por material_index e devolve o material do corpo.

    O Hunyuan entrega um mesh com material unico, entao aplicar vidro atinge
    tampa e rotulo junto. `segment_bottle.encontrar_corte` acha o ombro pelo
    pico de densidade de faces (ver docstring de la para a calibracao).

    Retorna None quando nao ha ombro discernivel — nesse caso o chamador deve
    cair no comportamento antigo (material unico para o frasco inteiro).
    """
    zs = alturas_das_faces(obj)
    z_corte, diag = encontrar_corte(zs)
    if z_corte is None:
        log(f"  ombro nao identificado ({diag.get('motivo')}) — vidro no frasco inteiro")
        return None

    garantir_dois_materiais(obj, debug=False)

    matriz = obj.matrix_world
    n_tampa = 0
    for poly in obj.data.polygons:
        if (matriz @ poly.center).z > z_corte:
            poly.material_index = 1
            n_tampa += 1
        else:
            poly.material_index = MATERIAL_CORPO
    n_corpo = len(obj.data.polygons) - n_tampa

    log(
        f"  segmentado no ombro z_rel={diag['z_rel_pico']:.2f} "
        f"(razao {diag['razao']:.2f}x): corpo={n_corpo}, tampa={n_tampa}"
    )
    return obj.data.materials[MATERIAL_CORPO]


def get_principled_bsdf(mat: bpy.types.Material) -> bpy.types.Node | None:
    """Retorna o nó Principled BSDF existente, ou None se não houver."""
    if not mat.use_nodes:
        mat.use_nodes = True
    for no in mat.node_tree.nodes:
        if no.type == "BSDF_PRINCIPLED":
            return no
    return None


# --------------------------------------------------------------------- aplicação

def aplicar_shader_vidro(mat: bpy.types.Material) -> None:
    """Substitui shader do material por Principled BSDF configurado como vidro.

    Recria a árvore de nós do material para garantir idempotência: rodar duas
    vezes no mesmo GLB não acumula nós nem reaproveita links antigos.
    """
    mat.use_nodes = True

    nos = mat.node_tree.nodes
    links = mat.node_tree.links
    nos.clear()

    saida = nos.new(type="ShaderNodeOutputMaterial")
    saida.location = (260, 0)
    bsdf = nos.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], saida.inputs["Surface"])

    # Parâmetros de vidro
    entrada_cor = bsdf.inputs.get("Base Color")
    if entrada_cor:
        entrada_cor.default_value = GLASS_PARAMS["base_color"]

    entrada_roughness = bsdf.inputs.get("Roughness")
    if entrada_roughness:
        entrada_roughness.default_value = GLASS_PARAMS["roughness"]

    entrada_ior = bsdf.inputs.get("IOR")
    if entrada_ior:
        entrada_ior.default_value = GLASS_PARAMS["ior"]

    # Blender 4+ usa "Transmission Weight"; 3.x usa "Transmission"
    for nome_trans in ("Transmission Weight", "Transmission"):
        entrada_trans = bsdf.inputs.get(nome_trans)
        if entrada_trans is not None:
            entrada_trans.default_value = GLASS_PARAMS["transmission"]
            break

    entrada_alpha = bsdf.inputs.get("Alpha")
    if entrada_alpha:
        entrada_alpha.default_value = GLASS_PARAMS["alpha"]

    # Permite renderização com transparência
    try:
        mat.surface_render_method = "BLENDED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass

    log(
        f"  shader de vidro aplicado: IOR={GLASS_PARAMS['ior']}, "
        f"transmission={GLASS_PARAMS['transmission']}, "
        f"roughness={GLASS_PARAMS['roughness']}"
    )


def aplicar_vidro_preservando_textura(mat: bpy.types.Material) -> None:
    """Converte um material texturizado em vidro PBR mantendo a textura.

    Não recria a árvore de nós: apenas ajusta Transmission/IOR/Roughness no
    Principled BSDF existente. A Image Texture conectada ao Base Color é
    preservada e passa a atuar como tinte do vidro — o azulado que a IA
    pintou vira a cor do vidro em vez de superfície opaca.

    Alpha fica em 1.0: transparência vem da transmissão (exportada como
    KHR_materials_transmission no glTF), não de alpha blend — alpha < 1
    somado a transmission dobraria a transparência em viewers PBR.

    Idempotente: setar os mesmos valores duas vezes produz o mesmo material.
    """
    bsdf = get_principled_bsdf(mat)
    if bsdf is None:
        log(f"  AVISO: material '{mat.name}' sem Principled BSDF — vidro não aplicado")
        return

    entrada_roughness = bsdf.inputs.get("Roughness")
    if entrada_roughness:
        entrada_roughness.default_value = GLASS_PARAMS["roughness"]

    entrada_ior = bsdf.inputs.get("IOR")
    if entrada_ior:
        entrada_ior.default_value = GLASS_PARAMS["ior"]

    for nome_trans in ("Transmission Weight", "Transmission"):
        entrada_trans = bsdf.inputs.get(nome_trans)
        if entrada_trans is not None:
            entrada_trans.default_value = GLASS_PARAMS["transmission"]
            break

    entrada_alpha = bsdf.inputs.get("Alpha")
    if entrada_alpha:
        entrada_alpha.default_value = 1.0

    # Metallic > 0 anula transmissão no glTF; zera por segurança.
    entrada_metallic = bsdf.inputs.get("Metallic")
    if entrada_metallic:
        entrada_metallic.default_value = 0.0

    try:
        mat.surface_render_method = "BLENDED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass

    log(
        f"  vidro com textura preservada: IOR={GLASS_PARAMS['ior']}, "
        f"transmission={GLASS_PARAMS['transmission']}, "
        f"roughness={GLASS_PARAMS['roughness']}"
    )


def aplicar_shader_tampa(mat: bpy.types.Material) -> None:
    """Aplica shader de plástico escuro à tampa (best-effort, sem garantia)."""
    bsdf = get_principled_bsdf(mat)
    if bsdf is None:
        return

    entrada_cor = bsdf.inputs.get("Base Color")
    if entrada_cor:
        entrada_cor.default_value = CAP_METALLIC_PARAMS["base_color"]

    entrada_roughness = bsdf.inputs.get("Roughness")
    if entrada_roughness:
        entrada_roughness.default_value = CAP_METALLIC_PARAMS["roughness"]

    entrada_metallic = bsdf.inputs.get("Metallic")
    if entrada_metallic:
        entrada_metallic.default_value = CAP_METALLIC_PARAMS["metallic"]

    log(f"  shader de tampa aplicado: roughness={CAP_METALLIC_PARAMS['roughness']}")


def aplicar_cor_liquido(
    mat: bpy.types.Material,
    cor: tuple[float, float, float, float],
) -> None:
    """Aplica cor ao material do líquido."""
    bsdf = get_principled_bsdf(mat)
    if bsdf is None:
        log("  AVISO: material de líquido sem Principled BSDF, cor não aplicada")
        return
    entrada_cor = bsdf.inputs.get("Base Color")
    if entrada_cor:
        entrada_cor.default_value = cor
    log(f"  cor do líquido aplicada: rgba={cor}")


# --------------------------------------------------------------------- detecção de tampa

def detectar_tampa(
    meshes: list[bpy.types.Object],
    corpo_obj: bpy.types.Object | None,
) -> bpy.types.Object | None:
    """Identifica a tampa como o mesh sem textura de maior posição Z.

    Heurística fraca — só considera confiável se a tampa está claramente
    acima do corpo (>20% da bounding box). Retorna None se inconcluso.
    """
    if corpo_obj is None or len(meshes) < 2:
        return None

    candidatos = []
    for obj in meshes:
        if obj is corpo_obj:
            continue
        if not obj.data.materials:
            continue
        mat = obj.data.materials[0]
        if mat is None or material_tem_textura_image(mat):
            continue
        candidatos.append(obj)

    if not candidatos:
        return None

    # Tampa = mesh com centro de bounding box mais alto (maior Z).
    tampa = max(candidatos, key=centro_z_bbox)

    # Verifica se está claramente acima do corpo
    if corpo_obj.bound_box and tampa.bound_box:
        altura_corpo = altura_bbox(corpo_obj)
        diferenca_z = centro_z_bbox(tampa) - centro_z_bbox(corpo_obj)
        if altura_corpo > 0 and diferenca_z < 0.2 * altura_corpo:
            return None

    return tampa


def centro_z_bbox(obj: bpy.types.Object) -> float:
    """Centro Z da bounding box em coordenadas mundo."""
    if not obj.bound_box:
        return obj.location.z
    pontos = [obj.matrix_world @ Vector(canto) for canto in obj.bound_box]
    zs = [ponto.z for ponto in pontos]
    return (min(zs) + max(zs)) / 2.0


def altura_bbox(obj: bpy.types.Object) -> float:
    """Altura Z da bounding box em coordenadas mundo."""
    if not obj.bound_box:
        return 0.0
    pontos = [obj.matrix_world @ Vector(canto) for canto in obj.bound_box]
    zs = [ponto.z for ponto in pontos]
    return max(zs) - min(zs)


# --------------------------------------------------------------------- main

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="refine_ai_mesh")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--body-mode",
        choices=("auto", "glass", "keep"),
        default="auto",
        help=(
            "auto = vidro só em corpo sem textura (legado); "
            "glass = força vidro, preservando textura se houver; "
            "keep = não toca nos materiais do corpo (frasco opaco)"
        ),
    )
    parser.add_argument(
        "--liquid-color", type=str, default=None,
        help="cor hex tipo '#FFAA00' aplicada ao material 'water' ou mesh 'Liquid'",
    )
    return parser.parse_args(get_argv_after_double_dash())


def main() -> int:
    args = parse_args()

    log(f"input        = {args.input}")
    log(f"output       = {args.output}")
    log(f"body-mode    = {args.body_mode}")
    log(f"liquid-color = {args.liquid_color}")

    if not args.input.exists():
        raise FileNotFoundError(f"GLB de entrada não encontrado: {args.input}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    log(f"meshes encontrados: {[o.name for o in meshes]}")

    corpo_obj: bpy.types.Object | None = None
    if args.body_mode == "keep":
        log("body-mode=keep: frasco opaco — materiais do corpo preservados")
    else:
        # Heurística legada: corpo sem Image Texture no Base Color.
        corpo_obj, corpo_mat = identificar_corpo_vidro(meshes)

        if corpo_obj is not None:
            log(f"Corpo identificado: '{corpo_obj.name}' (mat='{corpo_mat.name}')")
            aplicar_shader_vidro(corpo_mat)
        elif args.body_mode == "glass":
            # Saída texturizada do Hunyuan (caso normal com paint): aplica
            # transmissão ao maior mesh preservando a textura como tinte.
            corpo_obj, corpo_mat = identificar_corpo_texturizado(meshes)
            if corpo_obj is None:
                log("AVISO: nenhum mesh com material — exportando GLB inalterado")
            else:
                log(
                    f"Corpo texturizado identificado: '{corpo_obj.name}' "
                    f"(mat='{corpo_mat.name}')"
                )
                # Segmenta antes de aplicar: sem isso o vidro cobre tampa e
                # rótulo junto, porque o Hunyuan entrega material único.
                mat_segmentado = segmentar_corpo(corpo_obj)
                aplicar_vidro_preservando_textura(mat_segmentado or corpo_mat)
        else:
            log("AVISO: nenhum corpo de vidro identificado — exportando GLB inalterado")

    # Detecta tampa (best-effort) — só nos modos que mexem no corpo.
    if args.body_mode != "keep":
        tampa_obj = detectar_tampa(meshes, corpo_obj)
        if tampa_obj is not None and tampa_obj.data.materials:
            mat_tampa = tampa_obj.data.materials[0]
            if mat_tampa and not material_tem_textura_image(mat_tampa):
                log(f"Tampa identificada: '{tampa_obj.name}' (mat='{mat_tampa.name}')")
                aplicar_shader_tampa(mat_tampa)
            else:
                log(f"Tampa '{tampa_obj.name}' tem textura — preservando material")
        else:
            log("Tampa não identificada ou sem material próprio — ignorando")

    # Aplica cor no líquido se presente
    if args.liquid_color is not None:
        cor_rgba = parse_color_hex(args.liquid_color)
        mat_liquido = None

        # Procura mesh chamado "Liquid" primeiro
        for obj in meshes:
            if nome_base_blender(obj.name) == "liquid" and obj.data.materials:
                mat_liquido = obj.data.materials[0]
                break

        # Fallback: procura material chamado "water" ou "liquid"
        if mat_liquido is None:
            for mat in bpy.data.materials:
                if nome_base_blender(mat.name) in ("water", "liquid"):
                    mat_liquido = mat
                    break

        if mat_liquido:
            log(f"Material de líquido: '{mat_liquido.name}'")
            aplicar_cor_liquido(mat_liquido, cor_rgba)
        else:
            log("AVISO: nenhum mesh/material de líquido encontrado — --liquid-color ignorado")

    # Export
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Exportando: {args.output}")
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log("OK — refinamento concluído")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
