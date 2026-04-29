"""Limpa GLB gerado por IA (Hunyuan3D) antes do refinador de vidro.

Etapas (todas conservadoras — sem remesh agressivo):

1. Importa GLB.
2. Para cada mesh object:
   a. Separa por componentes conexos (loose parts).
   b. Calcula volume da bounding box de cada componente.
   c. Remove componentes com volume < min_island_ratio * volume_do_maior.
   d. Reagrupa o que sobrou em um único objeto.
3. Para cada mesh restante:
   a. Fecha buracos pequenos (até 4 vértices).
   b. Recalcula normais (orientação consistente para fora).
   c. Aplica shade_smooth + Auto Smooth 30°.
4. Emite STATS:islands=N,holes=M,faces=K em stdout para parsing.
5. Exporta GLB.

Roda em modo headless:

    blender.exe --background --python cleanup_mesh.py -- \\
        --input  raw.glb \\
        --output cleaned.glb \\
        [--min-island-ratio 0.05]
"""

from __future__ import annotations

import argparse
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)
from mathutils import Vector  # noqa: E402


# --------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[cleanup] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def selecionar_unico(obj: bpy.types.Object) -> None:
    """Seleciona apenas obj e o torna ativo. Garante que ops respeitem o contexto."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def volume_bbox(obj: bpy.types.Object) -> float:
    """Volume da bounding box em coordenadas mundo (proxy barato pra "tamanho")."""
    if not obj.bound_box:
        return 0.0
    pontos = [obj.matrix_world @ Vector(canto) for canto in obj.bound_box]
    xs = [p.x for p in pontos]
    ys = [p.y for p in pontos]
    zs = [p.z for p in pontos]
    return (
        (max(xs) - min(xs))
        * (max(ys) - min(ys))
        * (max(zs) - min(zs))
    )


def contar_furos_pequenos(obj: bpy.types.Object) -> int:
    """Conta loops de borda fechados com até 4 arestas — proxy para furos pequenos.

    Usado para reportar `holes_filled` antes/depois. Não depende do mesh estar
    em edit mode (lê obj.data direto).
    """
    if not obj.data or not obj.data.edges:
        return 0

    # Mapa aresta -> nº de polígonos que a usam. Aresta de borda = 1 polígono.
    contagem_polys = {edge.index: 0 for edge in obj.data.edges}
    for poligono in obj.data.polygons:
        for indice_aresta in poligono.edge_keys:
            # edge_keys retorna tuplas (v1, v2) — converte para índice.
            pass

    # Caminho mais robusto: usa edge.is_loose ou conta via polygons.
    arestas_borda = []
    edges_to_polys: dict[int, int] = {}
    for poligono in obj.data.polygons:
        for indice in poligono.loop_indices:
            loop = obj.data.loops[indice]
            edges_to_polys[loop.edge_index] = edges_to_polys.get(loop.edge_index, 0) + 1

    for edge in obj.data.edges:
        if edges_to_polys.get(edge.index, 0) <= 1:
            arestas_borda.append(edge)

    if not arestas_borda:
        return 0

    # Constrói grafo de arestas-borda e conta loops fechados pequenos.
    vertice_para_arestas: dict[int, list[int]] = {}
    for edge in arestas_borda:
        for v in edge.vertices:
            vertice_para_arestas.setdefault(v, []).append(edge.index)

    visitadas: set[int] = set()
    furos_pequenos = 0
    indice_para_aresta = {edge.index: edge for edge in arestas_borda}

    for aresta_inicial in arestas_borda:
        if aresta_inicial.index in visitadas:
            continue
        # BFS no loop de borda partindo desta aresta.
        loop_arestas = []
        pilha = [aresta_inicial.index]
        while pilha:
            idx = pilha.pop()
            if idx in visitadas:
                continue
            visitadas.add(idx)
            loop_arestas.append(idx)
            edge = indice_para_aresta[idx]
            for v in edge.vertices:
                for vizinha in vertice_para_arestas.get(v, []):
                    if vizinha not in visitadas:
                        pilha.append(vizinha)

        if 3 <= len(loop_arestas) <= 4:
            furos_pequenos += 1

    return furos_pequenos


# --------------------------------------------------------------------- etapas

def remover_ilhas_pequenas(
    obj: bpy.types.Object, *, min_island_ratio: float
) -> tuple[bpy.types.Object | None, int]:
    """Separa por loose parts, descarta as < min_island_ratio do maior, reagrupa.

    Retorna (objeto_resultante, n_ilhas_removidas). Se o mesh inteiro for
    descartado (caso raro), retorna (None, n_removidas).
    """
    if min_island_ratio <= 0.0:
        # Hunyuan frequentemente gera a superfície como milhares de pequenos
        # componentes adjacentes. Separar e remover por volume abre microfuros.
        # Ratio zero significa: preserve a geometria, só faça normais/furos.
        log("  remoção de ilhas desativada (min-island-ratio=0)")
        return obj, 0

    selecionar_unico(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.separate(type="LOOSE")
    except RuntimeError:
        # Mesh sem geometria (ou já é uma única ilha). separate falha mas tudo bem.
        pass
    bpy.ops.object.mode_set(mode="OBJECT")

    # Após separar, o objeto ativo + objetos selecionados (incluindo os novos)
    # representam todos os componentes. Coleta os MESH ones gerados pelo split.
    componentes = [
        candidato
        for candidato in bpy.context.selected_objects
        if candidato.type == "MESH"
    ]
    if not componentes:
        return obj, 0

    if len(componentes) == 1:
        # Só uma ilha — nada a remover.
        return componentes[0], 0

    volumes = [(c, volume_bbox(c)) for c in componentes]
    volumes.sort(key=lambda par: par[1], reverse=True)
    volume_maior = volumes[0][1]

    if volume_maior <= 0:
        return componentes[0], 0

    limite = min_island_ratio * volume_maior
    sobreviventes = []
    descartar = []
    for componente, volume in volumes:
        if volume >= limite:
            sobreviventes.append(componente)
        else:
            descartar.append(componente)

    # Remove ilhas pequenas.
    for componente in descartar:
        bpy.data.objects.remove(componente, do_unlink=True)

    if not sobreviventes:
        return None, len(descartar)

    # Reagrupa sobreviventes em um único objeto (join no maior).
    if len(sobreviventes) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for componente in sobreviventes:
            componente.select_set(True)
        bpy.context.view_layer.objects.active = sobreviventes[0]
        bpy.ops.object.join()
        principal = bpy.context.view_layer.objects.active
    else:
        principal = sobreviventes[0]

    return principal, len(descartar)


def fechar_furos_e_suavizar(obj: bpy.types.Object) -> int:
    """Fecha furos pequenos, recalcula normais, aplica shade_smooth.

    Retorna o número estimado de furos preenchidos (delta antes/depois).
    """
    furos_antes = contar_furos_pequenos(obj)

    selecionar_unico(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        # sides=4 → fecha apenas furos com até 4 arestas no perímetro.
        bpy.ops.mesh.fill_holes(sides=4)
    except RuntimeError as exc:
        log(f"  AVISO: fill_holes falhou: {exc}")

    try:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    except RuntimeError as exc:
        log(f"  AVISO: normals_make_consistent falhou: {exc}")

    bpy.ops.object.mode_set(mode="OBJECT")

    try:
        bpy.ops.object.shade_smooth()
    except RuntimeError as exc:
        log(f"  AVISO: shade_smooth falhou: {exc}")

    # Auto Smooth 30°: preserva arestas vivas em quinas (tampa, ombros do frasco).
    aplicar_auto_smooth(obj, angulo_graus=30.0)

    furos_depois = contar_furos_pequenos(obj)
    fechados = max(0, furos_antes - furos_depois)
    return fechados


def aplicar_auto_smooth(obj: bpy.types.Object, *, angulo_graus: float) -> None:
    """Aplica Auto Smooth.

    Blender 4.1+ removeu `mesh.use_auto_smooth` e `mesh.auto_smooth_angle`.
    A API moderna usa o operator `bpy.ops.object.shade_auto_smooth(angle=...)`.
    Mantemos fallback para 4.0 e anteriores.
    """
    angulo_rad = radians(angulo_graus)
    if hasattr(bpy.ops.object, "shade_auto_smooth"):
        try:
            selecionar_unico(obj)
            bpy.ops.object.shade_auto_smooth(angle=angulo_rad)
            return
        except RuntimeError as exc:
            log(f"  AVISO: shade_auto_smooth falhou: {exc}")

    # Fallback Blender < 4.1.
    if obj.data is not None and hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
        if hasattr(obj.data, "auto_smooth_angle"):
            obj.data.auto_smooth_angle = angulo_rad


def contar_faces(obj: bpy.types.Object) -> int:
    if not obj.data:
        return 0
    return len(obj.data.polygons)


# --------------------------------------------------------------------- main

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cleanup_mesh")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--min-island-ratio", type=float, default=0.0,
        help="ilhas com volume < ratio * maior_componente são removidas; 0 preserva todas (default 0)",
    )
    return parser.parse_args(get_argv_after_double_dash())


def main() -> int:
    args = parse_args()

    log(f"input             = {args.input}")
    log(f"output            = {args.output}")
    log(f"min-island-ratio  = {args.min_island_ratio}")

    if not args.input.exists():
        raise FileNotFoundError(f"GLB de entrada não encontrado: {args.input}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))

    meshes_iniciais = [o for o in bpy.data.objects if o.type == "MESH"]
    log(f"meshes encontrados: {[o.name for o in meshes_iniciais]}")

    total_ilhas_removidas = 0
    total_furos_fechados = 0

    # Processa cada mesh top-level. Após remoção/join, alguns objetos podem
    # ter sido recriados — reconsulta a cena após cada iteração.
    nomes_processados: set[str] = set()
    for mesh_obj in list(meshes_iniciais):
        if mesh_obj.name not in bpy.data.objects:
            # Já foi consumido por uma operação anterior (join, remove).
            continue
        if mesh_obj.name in nomes_processados:
            continue

        log(f"limpando '{mesh_obj.name}'")
        principal, ilhas_removidas = remover_ilhas_pequenas(
            mesh_obj, min_island_ratio=args.min_island_ratio
        )
        total_ilhas_removidas += ilhas_removidas

        if principal is None:
            log(f"  AVISO: '{mesh_obj.name}' descartado por completo")
            continue

        nomes_processados.add(principal.name)
        furos = fechar_furos_e_suavizar(principal)
        total_furos_fechados += furos
        log(
            f"  ilhas removidas={ilhas_removidas}, furos fechados={furos}, "
            f"faces={contar_faces(principal)}"
        )

    total_faces = sum(
        contar_faces(o) for o in bpy.data.objects if o.type == "MESH"
    )

    # STATS é parseado pelo wrapper Python — formato deve permanecer estável.
    log(
        f"STATS:islands={total_ilhas_removidas},"
        f"holes={total_furos_fechados},"
        f"faces={total_faces}"
    )

    # Export
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Exportando: {args.output}")
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )
    log("OK — limpeza concluída")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
