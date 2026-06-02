"""Renderiza 4 vistas cardeais de um GLB para alimentar pipelines como input sintético.

Convenção de eixos (Blender padrão):
- Frasco com base no plano XY, eixo Z = altura.
- Câmera olha para o origem; varia em torno do eixo Z (azimuth).

Vistas geradas:
- front : câmera em +Y, olhando para -Y  (vê a face +Y do frasco)
- right : câmera em +X, olhando para -X  (vê a face +X)
- back  : câmera em -Y, olhando para +Y  (vê a face -Y)
- left  : câmera em -X, olhando para +X  (vê a face -X)

A correspondência cardeal ⇄ direção segue a convenção do Hunyuan3D-2mv
(checkpoint multi-view). Quando o GLB de teste não está orientado da
mesma forma, --rotate-z permite girar antes de renderizar.

Roda em modo headless:

    blender.exe --background --python render_cardinal_views.py -- \\
        --input  template.glb \\
        --output-dir renders/ \\
        [--resolution 1024] \\
        [--rotate-z 0] \\
        [--bg-color 1.0,1.0,1.0]
"""

from __future__ import annotations

import argparse
import math
import sys
from math import radians
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)
from mathutils import Vector  # noqa: E402


# --------------------------------------------------------------------- helpers


def log(msg: str) -> None:
    print(f"[render-views] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    # Tudo após '--' é nosso; Blender consome o resto.
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument(
        "--rotate-z",
        type=float,
        default=0.0,
        help="Rotação prévia do modelo em torno de Z (graus). Útil quando "
        "o frasco não está orientado com a frente em +Y.",
    )
    parser.add_argument(
        "--bg-color",
        type=str,
        default="1.0,1.0,1.0",
        help="RGB do fundo (0-1, vírgula).",
    )
    parser.add_argument(
        "--camera-distance-factor",
        type=float,
        default=4.5,
        help=(
            "Distância da câmera em unidades do mundo. Modelo é normalizado "
            "para max_extent=1.6 (ver import_glb). Lente 50mm com sensor "
            "padrão (36×24mm, fit=AUTO em render quadrado) dá FOV ~27°. "
            "Para bottle de altura 1.6 caber em ~70% do frame: visible = "
            "1.6/0.7 = 2.29 → distance = 2.29/(2·tan(13.5°)) ≈ 4.77. "
            "Default 4.5 dá ~78% de coverage vertical (bom contraste com bg)."
        ),
    )
    parser.add_argument(
        "--orbit-count",
        type=int,
        default=0,
        help=(
            "Quantidade de vistas extras em órbita (azimuth uniforme). "
            "Usadas pelo MeshroomProcessor quando fotogrametria precisa de "
            "cobertura densa. 0 = só as 4 cardeais. Arquivos: "
            "orbit_DDD.png onde DDD é o ângulo zero-padded."
        ),
    )
    parser.add_argument(
        "--render-mode",
        type=str,
        choices=("matte", "realistic"),
        default="matte",
        help=(
            "Modo de renderização para benchmark dual:\n"
            "  matte: materiais substituídos por diffuse cinza opaco; "
            "    isola medição de geometria pura (padrão em papers como "
            "    Pix2Vox, DISN, GET3D). Silhueta sempre visível.\n"
            "  realistic: mantém materiais originais (vidro, transmissão); "
            "    usa HDRI + backlight para criar silhueta mesmo em vidro. "
            "    Simula condições de captura em app real."
        ),
    )
    parser.add_argument(
        "--hdri-path",
        type=Path,
        default=None,
        help=(
            "Caminho para HDRI .hdr/.exr (só usado em --render-mode=realistic). "
            "Se omitido, usa o HDRI padrão em eval/assets/studio_small_08_1k.hdr."
        ),
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: Path) -> Vector:
    """Importa GLB, centraliza na origem, escala para max_extent=1.6.

    Antes usávamos `diagonal=2.0` como target. Isso quebra com frascos
    elongados. Normalizando por `max_extent`, o frasco sempre cabe folgado
    no frame independente da proporção.

    PASSO CRÍTICO: o glTF importer cria um **empty parent** com rotação
    (Y-up→Z-up). Sem flatten, `obj.location` é em PARENT space mas nosso
    centróide é em WORLD space — a rotação descalibra a normalização. A
    primeira coisa que fazemos é `transform_apply(location, rotation, scale)`
    com toda a hierarquia selecionada (incluindo o empty), achatando tudo
    em world space. Depois disso obj.location e bbox vivem no mesmo
    sistema e a math do centróide funciona certo.
    """
    bpy.ops.import_scene.gltf(filepath=str(path))

    # PASSO 1: flatten hierarquia. Aplica transforms do empty parent
    # (rotação Y-up→Z-up) nos meshes filhos, depois desparenta tudo.
    bpy.ops.object.select_all(action="SELECT")
    for o in bpy.context.scene.objects:
        bpy.context.view_layer.objects.active = o
        break
    # parent_clear keep_transform: tira do empty mas preserva world position
    try:
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    except RuntimeError:
        pass  # se não há parent, ignora
    # Agora aplica transforms — depois disso obj.matrix_world == identity
    # (exceto location, que aplica em transform_apply abaixo).
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Remove o empty parent ocioso (se ainda existir).
    for o in list(bpy.context.scene.objects):
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)

    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise RuntimeError(f"GLB sem meshes: {path}")

    # PASSO 2: agora bbox em world space é honesto (sem parent transforms).
    min_v = Vector((float("inf"),) * 3)
    max_v = Vector((float("-inf"),) * 3)
    for obj in objs:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_v = Vector(min(a, b) for a, b in zip(min_v, world))
            max_v = Vector(max(a, b) for a, b in zip(max_v, world))

    centroid = (min_v + max_v) / 2
    extents = max_v - min_v
    max_extent = max(extents.x, extents.y, extents.z)
    log(
        f"Bounding box: extents=({extents.x:.3f}, {extents.y:.3f}, {extents.z:.3f}), "
        f"max={max_extent:.3f}, centroid={tuple(centroid)}"
    )

    # PASSO 3a: centraliza (shifta cada obj por -centroid) e BAKEIA o shift
    # imediatamente na mesh data. Depois disso obj.location == 0 e os
    # vertices estão em world space centrados em origem — terreno limpo
    # pra o resize que vem em seguida não acumular state.
    for obj in objs:
        obj.location -= centroid
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    # PASSO 3b: escala. Como obj.location == 0 agora, o pivot da resize
    # não importa muito — qualquer pivot na origem da o mesmo resultado.
    target_max_extent = 1.6
    scale = target_max_extent / max_extent if max_extent > 0 else 1.0
    bpy.context.scene.tool_settings.transform_pivot_point = "CURSOR"
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    bpy.ops.transform.resize(value=(scale, scale, scale))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Verifica bbox final (debug).
    min_v2 = Vector((float("inf"),) * 3)
    max_v2 = Vector((float("-inf"),) * 3)
    for obj in objs:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_v2 = Vector(min(a, b) for a, b in zip(min_v2, world))
            max_v2 = Vector(max(a, b) for a, b in zip(max_v2, world))
    e2 = max_v2 - min_v2
    c2 = (min_v2 + max_v2) / 2
    log(
        f"Após normalize: extents=({e2.x:.3f}, {e2.y:.3f}, {e2.z:.3f}), "
        f"centroid=({c2.x:.3f}, {c2.y:.3f}, {c2.z:.3f})"
    )

    return Vector((0, 0, 0))


def rotate_models(angle_deg: float) -> None:
    if angle_deg == 0:
        return
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.transform.rotate(value=radians(angle_deg), orient_axis="Z")
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)


def setup_world(bg_color: tuple[float, float, float]) -> None:
    """Configura o fundo do mundo com cor sólida. Usado pelo modo matte."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node is not None:
        bg_node.inputs["Color"].default_value = (*bg_color, 1.0)
        bg_node.inputs["Strength"].default_value = 1.0


def setup_world_hdri(hdri_path: Path) -> None:
    """Configura o fundo do mundo com HDRI (modo realistic).

    Substitui o nó `Background` por uma cadeia
    `Environment Texture (HDRI) → Background`. O HDRI fornece iluminação
    baseada em imagem e reflexos plausíveis nas superfícies de vidro,
    criando silhueta visível mesmo em materiais translúcidos.
    """
    if not hdri_path.exists():
        raise RuntimeError(
            f"HDRI não encontrado em {hdri_path}. "
            "Veja eval/assets/README.md para baixar."
        )
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    nodes.clear()
    env_tex = nodes.new(type="ShaderNodeTexEnvironment")
    env_tex.image = bpy.data.images.load(str(hdri_path))
    bg = nodes.new(type="ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0
    output = nodes.new(type="ShaderNodeOutputWorld")
    links.new(env_tex.outputs["Color"], bg.inputs["Color"])
    links.new(bg.outputs["Background"], output.inputs["Surface"])


def setup_lighting_matte() -> None:
    """Iluminação suave estilo estúdio (modo matte).

    Energias reduzidas (~200) pra preservar contraste entre o matte cinza
    escuro (0.25) e o fundo branco. Energias altas saturariam o matte pra
    quase-branco, perdendo silhueta.
    """
    for light_data in (
        ("Key", (3.0, -3.0, 4.0), 200.0),
        ("Fill", (-3.0, -2.0, 2.0), 100.0),
        ("Back", (0.0, 4.0, 3.0), 150.0),
    ):
        name, loc, energy = light_data
        light = bpy.data.lights.new(name=name, type="AREA")
        light.energy = energy
        light.size = 2.5
        obj = bpy.data.objects.new(name=name, object_data=light)
        obj.location = loc
        bpy.context.collection.objects.link(obj)


def setup_lighting_realistic() -> None:
    """Iluminação para modo realistic: HDRI (no world) + backlight forte.

    O HDRI no world fornece ambiente difuso/reflexos. Adicionamos UMA
    luz backlight de área grande atrás do frasco — técnica clássica de
    fotografia de produto pra criar silhueta visível em vidro
    transparente (a luz atravessa o vidro, criando halo nas bordas).
    """
    backlight = bpy.data.lights.new(name="BackLight", type="AREA")
    backlight.energy = 1500.0
    backlight.size = 5.0
    obj = bpy.data.objects.new(name="BackLight", object_data=backlight)
    obj.location = (0.0, 4.0, 0.0)
    obj.rotation_euler = (radians(90), 0.0, 0.0)  # aponta para -Y (frente)
    bpy.context.collection.objects.link(obj)

    # Fill lateral suave pra evitar sombras duras
    fill = bpy.data.lights.new(name="SideFill", type="AREA")
    fill.energy = 200.0
    fill.size = 3.0
    obj = bpy.data.objects.new(name="SideFill", object_data=fill)
    obj.location = (-2.0, -1.0, 1.5)
    bpy.context.collection.objects.link(obj)


def override_materials_matte() -> None:
    """Substitui todos os materiais por um BSDF difuso cinza ESCURO opaco.

    Modo matte: pra benchmark de geometria pura, materiais originais
    (vidro, transmissão, metal reflexivo) confundem rembg/SfM/segmentação.
    Substituí-los por matte garante silhueta visível e remove confounders
    de aparência. Convenção em papers de 3D reconstruction.

    Cor escolhida: cinza escuro (0.25, 0.25, 0.25) → contrasta forte com
    fundo branco puro (resultado: bottle ~80 sRGB, bg 255 sRGB). Garante
    silhueta detectável por rembg/SAM/threshold simples.
    """
    mat = bpy.data.materials.new(name="MatteOverride")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.25, 0.25, 0.25, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.8
        # Zerar transmissão (Blender 4.x usa "Transmission", 5.x "Transmission Weight")
        for key in ("Transmission", "Transmission Weight"):
            if key in bsdf.inputs:
                try:
                    bsdf.inputs[key].default_value = 0.0
                except (TypeError, AttributeError):
                    pass
        # Zerar metallic + specular pra evitar reflexos
        for key in ("Metallic", "Specular IOR Level", "Specular"):
            if key in bsdf.inputs:
                try:
                    bsdf.inputs[key].default_value = 0.0
                except (TypeError, AttributeError):
                    pass

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    log("Materiais substituídos por MatteOverride (cinza diffuse opaco)")


def create_camera(distance: float):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 50  # mm
    cam_obj = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    return cam_obj


def look_at(cam_obj, target: Vector) -> None:
    direction = target - cam_obj.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()


def configure_render(resolution: int, render_mode: str = "matte") -> None:
    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100

    # ---- View transform / color management ----
    # Blender default é "Filmic" (Filmic Log Encoding) que comprime highlights.
    # Resultado: bg color (1,1,1) com strength=1 renderiza como cinza ~200
    # em sRGB, não branco puro 255. Pra benchmark MATTE precisamos branco
    # puro pra ter silhueta de alto contraste (algoritmos de segmentação
    # esperam isso). Usamos "Standard" no matte (linear → sRGB direto) e
    # mantemos "AgX" / "Filmic" no realistic (preserva detalhe em vidro).
    if render_mode == "matte":
        try:
            scene.view_settings.view_transform = "Standard"
            log("View transform: Standard (preserva contraste pra silhueta)")
        except (TypeError, ValueError, AttributeError):
            log("View transform: não consegui setar 'Standard'")
    # Para realistic: deixa o padrão do Blender (AgX/Filmic).

    # Em Blender 4.2-4.x o engine é EEVEE_NEXT; em 5.0+ voltou a ser EEVEE.
    # Tenta os dois nessa ordem.
    for engine_id in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine_id
            log(f"Engine: {engine_id}")
            break
        except (TypeError, ValueError):
            continue

    # Samples baixos — pra benchmark, qualidade visual fina não importa.
    # Cada vista cai pra ~1-3s em vez de 30-45s.
    for attr_obj_name in ("eevee", "eevee_next"):
        attr_obj = getattr(scene, attr_obj_name, None)
        if attr_obj is None:
            continue
        try:
            attr_obj.taa_render_samples = 16
        except AttributeError:
            pass
        try:
            attr_obj.use_gtao = True
        except AttributeError:
            pass


def render_view(cam_obj, name: str, position: Vector, target: Vector, out_dir: Path) -> Path:
    cam_obj.location = position
    look_at(cam_obj, target)
    out_path = out_dir / f"{name}.png"
    bpy.context.scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    log(f"Renderizado: {name} → {out_path}")
    return out_path


# ----------------------------------------------------------------------- main


CARDINAL_POSITIONS = {
    "front": Vector((0.0, -1.0, 0.0)),  # câmera em -Y olhando +Y → vê face frontal
    "right": Vector((1.0, 0.0, 0.0)),
    "back": Vector((0.0, 1.0, 0.0)),
    "left": Vector((-1.0, 0.0, 0.0)),
}


# Cardeais em graus de azimuth (sentido anti-horário a partir de "front"):
# front=0°, right=90°, back=180°, left=270°.
_CARDINAL_AZIMUTHS = (0.0, 90.0, 180.0, 270.0)


def orbit_position(azimuth_deg: float) -> Vector:
    """Posição da câmera para um azimuth em graus.

    Convenção: 0° = front (camera em -Y), 90° = right (camera em +X),
    180° = back, 270° = left. Mesma altura das cardeais.
    """
    rad = math.radians(azimuth_deg)
    return Vector((math.sin(rad), -math.cos(rad), 0.0))


def orbit_azimuths(count: int) -> list[float]:
    """Retorna `count` azimuths uniformes pulando os 4 cardeais.

    Ex: count=24 → tenta 0°, 15°, 30°, ..., 345° (24 valores uniformes em 15°),
    mas remove 0°, 90°, 180°, 270° (já são cardeais), restando 20 ângulos.
    Para garantir EXATAMENTE `count` ângulos não-cardeais, usamos resolução
    maior e filtramos.
    """
    if count <= 0:
        return []
    # Resolução de partição: subdivide em count + 4 (4 a mais p/ compensar
    # os cardeais removidos), e descarta os que caem em múltiplos de 90°.
    step = 360.0 / (count + 4)
    angles: list[float] = []
    azimuth = 0.0
    while len(angles) < count:
        # Pequena tolerância (1e-3) para evitar problemas de ponto-flutuante
        # quando count + 4 é múltiplo de 4 (ex: count=24 → step=360/28).
        is_cardinal = any(
            abs((azimuth - c) % 360.0) < 1e-3
            or abs((azimuth - c) % 360.0 - 360.0) < 1e-3
            for c in _CARDINAL_AZIMUTHS
        )
        if not is_cardinal:
            angles.append(azimuth)
        azimuth += step
        if azimuth >= 360.0:
            azimuth -= 360.0
            if not angles:
                break  # safety guard
    return angles[:count]


_DEFAULT_HDRI_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "studio_small_08_1k.hdr"
)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    bg_color = tuple(float(x) for x in args.bg_color.split(","))
    if len(bg_color) != 3:
        raise SystemExit("--bg-color precisa de 3 valores separados por vírgula")

    log(f"Carregando {args.input} (modo={args.render_mode})")
    clear_scene()
    target = import_glb(args.input)
    rotate_models(args.rotate_z)

    # Setup específico por modo.
    if args.render_mode == "matte":
        override_materials_matte()
        setup_world(bg_color)
        setup_lighting_matte()
    elif args.render_mode == "realistic":
        # Mantém materiais originais (vidro, transmissão).
        hdri = args.hdri_path or _DEFAULT_HDRI_PATH
        setup_world_hdri(hdri)
        setup_lighting_realistic()
    else:
        raise SystemExit(f"render_mode desconhecido: {args.render_mode!r}")

    configure_render(args.resolution, render_mode=args.render_mode)

    distance = args.camera_distance_factor
    cam = create_camera(distance)

    rendered: list[Path] = []

    # 1. Vistas cardeais — sempre renderizadas (IA/Blander dependem delas).
    for name, direction in CARDINAL_POSITIONS.items():
        position = direction * distance + Vector((0, 0, 0.1))  # leve elevação
        rendered.append(render_view(cam, name, position, target, args.output_dir))

    # 2. Vistas orbit — extras pra Meshroom (azimuth uniforme, mesma altura).
    if args.orbit_count > 0:
        log(f"Renderizando {args.orbit_count} vistas orbit (azimuth uniforme)...")
        for azimuth in orbit_azimuths(args.orbit_count):
            direction = orbit_position(azimuth)
            position = direction * distance + Vector((0, 0, 0.1))
            name = f"orbit_{int(round(azimuth)):03d}"
            rendered.append(render_view(cam, name, position, target, args.output_dir))

    log(f"Concluído: {len(rendered)} vistas em {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
