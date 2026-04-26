"""Customiza um template GLB normalizado e exporta um GLB final.

Roda dentro do Blender em modo headless:

    blender.exe --background --python customize_template.py -- \
        --template path/to/rectangular_basic.glb \
        --output   path/to/storage/models/<jobId>.glb \
        --label-image path/to/foto_frontal.jpg \
        --liquid-color #FFAA00

Convenção do template (definida pelo script de normalização):
- Nó `Bottle`  → corpo do frasco (vidro)
- Nó `Liquid`  → líquido interno; material chamado `water`
- Nó `Cap`     → tampa
- Nó `Label`   → plano frontal; material chamado `LabelMaterial`

O script é tolerante a templates incompletos: se algum slot esperado não
existir, ele apenas registra um aviso e segue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # noqa: E402  (só existe dentro do Blender)


# --------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[customize] {msg}", flush=True)


def parse_color_hex(value: str) -> tuple[float, float, float, float]:
    """Aceita '#RRGGBB' ou 'RRGGBB' e devolve (r, g, b, a) em [0,1]."""
    raw = value.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"cor hex deve ter 6 dígitos: '{value}'")
    r = int(raw[0:2], 16) / 255.0
    g = int(raw[2:4], 16) / 255.0
    b = int(raw[4:6], 16) / 255.0
    return (r, g, b, 1.0)


def get_argv_after_double_dash() -> list[str]:
    """Blender passa nossos args depois de '--'. Antes disso são args do Blender."""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


# --------------------------------------------------------------------- etapas

def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_template(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"template não encontrado: {path}")
    log(f"Importando template: {path}")
    bpy.ops.import_scene.gltf(filepath=str(path))


def find_material(name: str) -> bpy.types.Material | None:
    """Procura material pelo nome base (ignora sufixos .001, .002...)."""
    base = name.split(".")[0]
    for mat in bpy.data.materials:
        if mat.name.split(".")[0] == base:
            return mat
    return None


def get_principled_bsdf(material: bpy.types.Material) -> bpy.types.Node | None:
    if not material.use_nodes:
        material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def apply_label_texture(material: bpy.types.Material, image_path: Path) -> None:
    """Conecta a imagem ao Base Color do material da label."""
    bsdf = get_principled_bsdf(material)
    if bsdf is None:
        log(f"  AVISO: material '{material.name}' sem Principled BSDF, pulando textura")
        return

    image = bpy.data.images.load(str(image_path), check_existing=True)

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    tex_node = nodes.new(type="ShaderNodeTexImage")
    tex_node.image = image
    tex_node.location = (bsdf.location.x - 350, bsdf.location.y)

    base_color_input = bsdf.inputs.get("Base Color")
    if base_color_input is None:
        log("  AVISO: BSDF sem Base Color, pulando")
        return
    links.new(tex_node.outputs["Color"], base_color_input)
    log(f"  textura aplicada na label: {image_path.name}")


def apply_liquid_color(
    material: bpy.types.Material,
    color: tuple[float, float, float, float],
) -> None:
    bsdf = get_principled_bsdf(material)
    if bsdf is None:
        log(f"  AVISO: material '{material.name}' sem Principled BSDF, pulando cor")
        return
    base_color_input = bsdf.inputs.get("Base Color")
    if base_color_input is None:
        return
    base_color_input.default_value = color
    log(f"  cor do líquido aplicada: rgba={color}")


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


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(prog="customize_template")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label-image", type=Path, default=None)
    parser.add_argument("--liquid-color", type=str, default=None,
                        help="cor hex tipo '#FFAA00' aplicada ao material 'water'")
    args = parser.parse_args(get_argv_after_double_dash())

    log(f"template       = {args.template}")
    log(f"output         = {args.output}")
    log(f"label-image    = {args.label_image}")
    log(f"liquid-color   = {args.liquid_color}")

    reset_scene()
    import_template(args.template)

    if args.label_image is not None:
        if not args.label_image.exists():
            raise FileNotFoundError(f"label-image não encontrada: {args.label_image}")
        label_mat = find_material("LabelMaterial")
        if label_mat is None:
            log("  AVISO: template não tem LabelMaterial — label não aplicada")
        else:
            apply_label_texture(label_mat, args.label_image)

    if args.liquid_color is not None:
        rgba = parse_color_hex(args.liquid_color)
        liquid_mat = find_material("water")
        if liquid_mat is None:
            log("  AVISO: template não tem material 'water' — cor não aplicada")
        else:
            apply_liquid_color(liquid_mat, rgba)

    export_glb(args.output)
    log("OK — customização concluída")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
