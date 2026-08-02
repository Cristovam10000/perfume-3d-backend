"""Segmenta o GLB do Hunyuan em corpo e tampa, dando material proprio a cada um.

Motivacao: o Hunyuan entrega **um mesh com um unico material**. Qualquer
alteracao de material (vidro PBR, textura do topo) atinge o frasco inteiro —
rotulo, tampa e liquido junto. Este script separa as duas regioes por
material_index para que os stages seguintes ajam so onde devem.

Sinal usado — pico de densidade de faces
----------------------------------------
Uma superficie horizontal (o "ombro" onde o corpo termina) concentra muitas
faces numa faixa estreita de Z. Medido nos GLBs reais do projeto:

    frasco     baseline   pico      z_rel   razao
    GRAND      ~22.000    48.289    0.67    2.2x
    Vivacite   ~16.000    42.272    0.67    2.6x
    ASAD       ~20.000    58.358    0.75    2.9x

Alternativas descartadas por medicao:
- **raio por fatia**: o ASAD tem tampa do mesmo diametro do corpo (perfil
  plano de 0.12 a 0.92), entao nao ha gargalo geometrico para achar.
- **cor da textura**: o ASAD e preto no corpo e na tampa, e tem faixas
  douradas decorativas em varias alturas — multiplos candidatos ambiguos.

O pico e procurado apenas na faixa [Z_MIN_BUSCA, Z_MAX_BUSCA] porque o topo
e o fundo do frasco tambem sao superficies horizontais e produzem picos
maiores ainda, que nao interessam.

Roda dentro do Blender headless:

    blender.exe --background --python segment_bottle.py -- \\
        --input  raw.glb \\
        --output segmented.glb \\
        [--debug-colors]
"""

from __future__ import annotations

import argparse
import sys

import bpy  # noqa: E402

# Faixa de busca do ombro, em altura relativa. Fora dela ficam o fundo (0.0) e
# a face superior da tampa (1.0), que sao horizontais e dariam falso positivo.
Z_MIN_BUSCA = 0.40
Z_MAX_BUSCA = 0.88

# Numero de fatias do histograma. 24 deu pico limpo nos tres frascos medidos;
# mais fatias fragmentam o pico, menos fatias borram a posicao.
N_FATIAS = 24

# Razao minima entre o pico e a mediana da faixa para aceitar a deteccao.
# Abaixo disso o frasco nao tem ombro discernivel e a segmentacao e abortada.
RAZAO_MINIMA = 1.5

MATERIAL_CORPO = 0
MATERIAL_TAMPA = 1

COR_DEBUG_CORPO = (0.85, 0.15, 0.15, 1.0)
COR_DEBUG_TAMPA = (0.15, 0.35, 0.90, 1.0)


def log(msg: str) -> None:
    print(f"[segment] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="segment_bottle")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--debug-colors",
        action="store_true",
        help="pinta corpo de vermelho e tampa de azul para conferencia visual",
    )
    return parser.parse_args(get_argv_after_double_dash())


def maior_mesh() -> bpy.types.Object:
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("[segment] nenhum mesh no arquivo")
    return max(meshes, key=lambda o: len(o.data.polygons))


def alturas_das_faces(obj: bpy.types.Object) -> list[float]:
    """Z do centro de cada face, em coordenadas de mundo."""
    mw = obj.matrix_world
    return [(mw @ poly.center).z for poly in obj.data.polygons]


def encontrar_corte(zs: list[float]) -> tuple[float | None, dict]:
    """Acha a altura do ombro pelo pico de densidade de faces.

    Retorna (z_corte_absoluto, diagnostico). z_corte e None quando nenhum
    pico supera RAZAO_MINIMA — nesse caso o chamador deve nao segmentar.
    """
    z_min, z_max = min(zs), max(zs)
    span = z_max - z_min
    if span <= 0:
        return None, {"motivo": "mesh degenerado (span Z zero)"}

    contagem = [0] * N_FATIAS
    for z in zs:
        idx = int((z - z_min) / span * N_FATIAS)
        contagem[min(idx, N_FATIAS - 1)] += 1

    i_min = int(Z_MIN_BUSCA * N_FATIAS)
    i_max = int(Z_MAX_BUSCA * N_FATIAS)
    faixa = contagem[i_min:i_max]
    if not faixa:
        return None, {"motivo": "faixa de busca vazia"}

    pico = max(faixa)
    i_pico = i_min + faixa.index(pico)
    ordenada = sorted(faixa)
    mediana = ordenada[len(ordenada) // 2] or 1
    razao = pico / mediana

    diagnostico = {
        "z_rel_pico": i_pico / N_FATIAS,
        "faces_pico": pico,
        "mediana_faixa": mediana,
        "razao": razao,
    }

    if razao < RAZAO_MINIMA:
        diagnostico["motivo"] = f"razao {razao:.2f} < {RAZAO_MINIMA}"
        return None, diagnostico

    # Corta no topo da fatia do pico: o ombro pertence ao corpo, o que esta
    # acima dele e tampa/gargalo.
    z_corte = z_min + span * (i_pico + 1) / N_FATIAS
    return z_corte, diagnostico


def garantir_dois_materiais(obj: bpy.types.Object, debug: bool) -> None:
    """Deixa o objeto com dois slots: [0]=corpo, [1]=tampa.

    A tampa recebe uma copia do material original para herdar a textura; assim
    a aparencia nao muda ate que algum stage altere um dos dois.
    """
    malha = obj.data
    if not malha.materials:
        base = bpy.data.materials.new("Material_0")
        base.use_nodes = True
        malha.materials.append(base)

    if len(malha.materials) < 2:
        copia = malha.materials[0].copy()
        copia.name = f"{malha.materials[0].name}_Tampa"
        malha.materials.append(copia)

    if debug:
        for slot, cor in (
            (MATERIAL_CORPO, COR_DEBUG_CORPO),
            (MATERIAL_TAMPA, COR_DEBUG_TAMPA),
        ):
            mat = malha.materials[slot]
            mat.use_nodes = True
            nos = mat.node_tree.nodes
            nos.clear()
            saida = nos.new("ShaderNodeOutputMaterial")
            bsdf = nos.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Base Color"].default_value = cor
            bsdf.inputs["Roughness"].default_value = 0.5
            mat.node_tree.links.new(bsdf.outputs["BSDF"], saida.inputs["Surface"])


def main() -> int:
    args = parse_args()
    log(f"input  = {args.input}")
    log(f"output = {args.output}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.input)

    obj = maior_mesh()
    log(f"mesh   = '{obj.name}' ({len(obj.data.polygons)} faces)")

    zs = alturas_das_faces(obj)
    z_corte, diag = encontrar_corte(zs)

    if z_corte is None:
        log(f"AVISO: ombro nao identificado ({diag.get('motivo')}) — exportando sem segmentar")
        log(f"SEGMENT:ok=0,corpo=0,tampa=0")
    else:
        log(
            f"ombro em z_rel={diag['z_rel_pico']:.2f} "
            f"({diag['faces_pico']} faces vs mediana {diag['mediana_faixa']}, "
            f"razao {diag['razao']:.2f}x)"
        )
        garantir_dois_materiais(obj, args.debug_colors)

        mw = obj.matrix_world
        n_tampa = 0
        for poly in obj.data.polygons:
            if (mw @ poly.center).z > z_corte:
                poly.material_index = MATERIAL_TAMPA
                n_tampa += 1
            else:
                poly.material_index = MATERIAL_CORPO
        n_corpo = len(obj.data.polygons) - n_tampa

        pct = 100.0 * n_tampa / max(len(obj.data.polygons), 1)
        log(f"corpo={n_corpo} faces, tampa={n_tampa} faces ({pct:.1f}% na tampa)")
        log(f"SEGMENT:ok=1,corpo={n_corpo},tampa={n_tampa}")

    bpy.ops.export_scene.gltf(
        filepath=args.output,
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log("OK — segmentacao concluida")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
