"""Renderiza um PNG de vitrine do GLB final, para o card do produto no app.

A coluna `modelos_3d_produto.caminho_imagem_preview` existe desde o schema
original e nunca foi preenchida: o backend a devolvia como `previewImg`, o app
ja a carregava no modelo, e ela era sempre nula — entao o card caia num
gradiente rosa generico. Este script fecha essa lacuna.

Decisoes:

- **Fundo transparente** (RGBA). O card do estoque tem fundo proprio; um PNG
  com alpha assenta sobre qualquer cor sem moldura branca em volta.
- **Sem HDRI.** O mundo e um gradiente neutro montado por nodes e a iluminacao
  sao quatro area lights. Evita depender de `eval/assets/*.hdr`, que e material
  de benchmark, e deixa o resultado deterministico.
- **Angulo de catalogo** (3/4, ~12 graus de elevacao): mostra frente, lateral e
  ombro do frasco de uma vez. Mesma camera do showcase usado nas inspecoes.
- **Normaliza escala e centro** antes de mirar: o GLB do Hunyuan nao vem com
  tamanho nem origem padronizados, entao enquadrar por valores fixos daria
  recortes diferentes a cada frasco.

Roda dentro do Blender headless:

    blender.exe --background --python render_preview.py -- \\
        --input path/to/final.glb \\
        --output path/to/preview.png \\
        [--resolution 512]
"""

from __future__ import annotations

import argparse
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

# Extensao do maior eixo depois de normalizar. A camera e posicionada em funcao
# disso, entao os dois numeros andam juntos.
EXTENSAO_ALVO = 1.6
# Com lente de 55mm em sensor de 36mm o campo vertical e ~36,4 graus. A esta
# distancia o frasco ocupa ~80% da altura do quadro: cheio o bastante para um
# card pequeno, com margem para o giro de 3/4 nao encostar na borda.
DISTANCIA_CAMERA = 3.1
ELEVACAO_GRAUS = 12.0
AZIMUTE_GRAUS = 35.0


def log(mensagem: str) -> None:
    print(f"[render_preview] {mensagem}", flush=True)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Renderiza o preview de um GLB.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=512)
    return parser.parse_args(argv)


def importar_e_normalizar(caminho: Path) -> None:
    """Importa o GLB, achata a hierarquia, centraliza e normaliza a escala.

    O importador glTF cria um empty pai com a rotacao Y-up -> Z-up. Sem achatar
    a hierarquia, `obj.location` vive em parent space e a normalizacao sai
    torta — mesmo cuidado do `render_cardinal_views.py`.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(caminho))

    bpy.ops.object.select_all(action="SELECT")
    for objeto in bpy.context.scene.objects:
        bpy.context.view_layer.objects.active = objeto
        break
    try:
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    except RuntimeError:
        pass
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for objeto in list(bpy.context.scene.objects):
        if objeto.type == "EMPTY":
            bpy.data.objects.remove(objeto, do_unlink=True)

    malhas = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not malhas:
        raise RuntimeError(f"GLB sem meshes: {caminho}")

    minimo = Vector((float("inf"),) * 3)
    maximo = Vector((float("-inf"),) * 3)
    for objeto in malhas:
        for canto in objeto.bound_box:
            mundo = objeto.matrix_world @ Vector(canto)
            minimo = Vector(min(a, b) for a, b in zip(minimo, mundo))
            maximo = Vector(max(a, b) for a, b in zip(maximo, mundo))
    centro = (minimo + maximo) / 2
    extensao = maximo - minimo
    maior = max(extensao.x, extensao.y, extensao.z)

    for objeto in malhas:
        objeto.location -= centro
    bpy.ops.object.select_all(action="DESELECT")
    for objeto in malhas:
        objeto.select_set(True)
    bpy.context.view_layer.objects.active = malhas[0]
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    escala = EXTENSAO_ALVO / maior if maior > 0 else 1.0
    bpy.context.scene.tool_settings.transform_pivot_point = "CURSOR"
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    bpy.ops.transform.resize(value=(escala,) * 3)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    log(f"malhas={len(malhas)} extensao={maior:.3f} escala={escala:.3f}")


def montar_mundo() -> None:
    """Gradiente neutro: ilumina e reflete sem aparecer no render (alpha)."""
    mundo = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = mundo
    mundo.use_nodes = True
    nodes, links = mundo.node_tree.nodes, mundo.node_tree.links
    nodes.clear()

    gradiente = nodes.new("ShaderNodeTexGradient")
    gradiente.gradient_type = "EASING"
    rampa = nodes.new("ShaderNodeValToRGB")
    rampa.color_ramp.elements[0].color = (0.28, 0.28, 0.30, 1.0)
    rampa.color_ramp.elements[1].color = (0.92, 0.92, 0.94, 1.0)
    fundo = nodes.new("ShaderNodeBackground")
    fundo.inputs["Strength"].default_value = 1.1
    saida = nodes.new("ShaderNodeOutputWorld")

    links.new(gradiente.outputs["Color"], rampa.inputs["Fac"])
    links.new(rampa.outputs["Color"], fundo.inputs["Color"])
    links.new(fundo.outputs["Background"], saida.inputs["Surface"])

    bpy.context.scene.render.film_transparent = True


def montar_luzes() -> None:
    for nome, local, energia in (
        ("Key", (3.0, -3.0, 3.5), 400.0),
        ("Fill", (-3.5, -1.5, 1.5), 180.0),
        ("Rim", (0.0, 3.5, 2.5), 300.0),
        ("Top", (0.0, 0.0, 4.5), 250.0),
    ):
        dados = bpy.data.lights.new(name=nome, type="AREA")
        dados.energy = energia
        dados.size = 3.0
        objeto = bpy.data.objects.new(name=nome, object_data=dados)
        objeto.location = local
        bpy.context.collection.objects.link(objeto)


def configurar_render(resolucao: int) -> None:
    cena = bpy.context.scene
    cena.render.image_settings.file_format = "PNG"
    cena.render.image_settings.color_mode = "RGBA"
    cena.render.resolution_x = resolucao
    cena.render.resolution_y = resolucao
    cena.render.resolution_percentage = 100
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            cena.render.engine = engine
            break
        except (TypeError, ValueError):
            continue
    for atributo in ("eevee", "eevee_next"):
        eevee = getattr(cena, atributo, None)
        if eevee is None:
            continue
        for chave, valor in (("taa_render_samples", 64), ("use_gtao", True)):
            try:
                setattr(eevee, chave, valor)
            except AttributeError:
                pass


def posicionar_camera() -> None:
    from math import cos, sin

    dados = bpy.data.cameras.new("Cam")
    dados.lens = 55
    camera = bpy.data.objects.new("Cam", dados)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    azimute = radians(AZIMUTE_GRAUS)
    elevacao = radians(ELEVACAO_GRAUS)
    camera.location = Vector((
        sin(azimute) * DISTANCIA_CAMERA * cos(elevacao),
        -cos(azimute) * DISTANCIA_CAMERA * cos(elevacao),
        DISTANCIA_CAMERA * sin(elevacao),
    ))
    direcao = Vector((0.0, 0.0, 0.0)) - camera.location
    camera.rotation_euler = direcao.to_track_quat("-Z", "Y").to_euler()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        log(f"ERRO: GLB de entrada nao encontrado: {args.input}")
        return 1

    importar_e_normalizar(args.input)
    montar_mundo()
    montar_luzes()
    configurar_render(args.resolution)
    posicionar_camera()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(args.output)
    bpy.ops.render.render(write_still=True)

    if not args.output.exists():
        log("ERRO: render nao produziu arquivo")
        return 1
    log(f"OK — {args.output} ({args.output.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — o exit code e o contrato com o wrapper
        log(f"ERRO: {exc}")
        sys.exit(1)
