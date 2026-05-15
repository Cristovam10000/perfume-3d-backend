"""Fit a normalized perfume template to silhouette measurements.

Runs inside Blender headless:

    blender --background --python fit_template.py -- \
        --template rectangular_basic.glb \
        --output job.glb \
        --body-width-scale 1.10 \
        --body-depth-scale 0.85 \
        --height-scale 0.95 \
        --cap-width-scale 0.90 \
        --cap-height-ratio 0.16 \
        --label-image label.png \
        --top-image top.png \
        --liquid-color #88AADD

The script is intentionally conservative: it deforms known template parts
(`Bottle`, `Liquid`, `Cap`, `Label`) by world-space scaling and keeps the
original mesh topology. This is safer than remeshing and gives the backend a
real fitting stage without requiring a trained 3D model.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402


UP_AXIS = Vector((0.0, 0.0, 1.0))


def log(msg: str) -> None:
    print(f"[fit-template] {msg}", flush=True)


def get_argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fit_template")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fit-plan", type=Path, default=None)
    parser.add_argument("--body-width-scale", type=float, default=1.0)
    parser.add_argument("--body-depth-scale", type=float, default=1.0)
    parser.add_argument("--height-scale", type=float, default=1.0)
    parser.add_argument("--cap-width-scale", type=float, default=1.0)
    parser.add_argument("--cap-height-ratio", type=float, default=0.16)
    parser.add_argument("--label-image", type=Path, default=None)
    parser.add_argument("--top-image", type=Path, default=None)
    parser.add_argument("--liquid-color", type=str, default=None)
    return parser.parse_args(get_argv_after_double_dash())


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_template(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"template nao encontrado: {path}")
    log(f"importando template: {path}")
    bpy.ops.import_scene.gltf(filepath=str(path))
    remove_default_cube_if_present()


def remove_default_cube_if_present() -> None:
    """Remove the accidental Blender default cube from normalized templates."""
    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or not base_name(obj.name).startswith("Cube"):
            continue
        bpy.data.objects.remove(obj, do_unlink=True)
        log("objeto auxiliar 'Cube' removido antes do fitting")


def remove_default_cube_meshes() -> None:
    remove_default_cube_if_present()
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0 and mesh.name.split(".")[0].startswith("Cube"):
            bpy.data.meshes.remove(mesh)


def export_glb(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    remove_default_cube_meshes()
    bpy.ops.object.select_all(action="SELECT")
    log(f"exportando: {output}")
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
    )


def mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if obj.type == "MESH"]


def clear_meshes() -> None:
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)


def base_name(name: str) -> str:
    return name.split(".")[0]


def find_object(*names: str) -> bpy.types.Object | None:
    expected = {name.lower() for name in names}
    for obj in mesh_objects():
        if base_name(obj.name).lower() in expected:
            return obj
    return None


def bbox_world(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_v = Vector(
        (
            min(p.x for p in points),
            min(p.y for p in points),
            min(p.z for p in points),
        )
    )
    max_v = Vector(
        (
            max(p.x for p in points),
            max(p.y for p in points),
            max(p.z for p in points),
        )
    )
    return min_v, max_v


def bbox_volume(obj: bpy.types.Object) -> float:
    min_v, max_v = bbox_world(obj)
    size = max_v - min_v
    return max(size.x, 0.0) * max(size.y, 0.0) * max(size.z, 0.0)


def find_body() -> bpy.types.Object | None:
    explicit = find_object("Bottle", "Body", "Frasco")
    if explicit is not None:
        return explicit
    meshes = mesh_objects()
    return max(meshes, key=bbox_volume) if meshes else None


def translate_world(obj: bpy.types.Object, delta: Vector) -> None:
    obj.matrix_world.translation = obj.matrix_world.translation + delta


def scale_mesh_world(
    obj: bpy.types.Object,
    sx: float,
    sy: float,
    sz: float,
    *,
    anchor_bottom: bool = True,
) -> None:
    """Scale mesh vertices in world space around bbox center/bottom."""
    min_v, max_v = bbox_world(obj)
    center = (min_v + max_v) * 0.5
    anchor_z = min_v.z if anchor_bottom else center.z
    inv = obj.matrix_world.inverted()

    for vertex in obj.data.vertices:
        p = obj.matrix_world @ vertex.co
        fitted = Vector(
            (
                center.x + (p.x - center.x) * sx,
                center.y + (p.y - center.y) * sy,
                anchor_z + (p.z - anchor_z) * sz,
            )
        )
        vertex.co = inv @ fitted

    obj.data.update()


def fit_geometry(args: argparse.Namespace) -> None:
    body = find_body()
    if body is None:
        raise RuntimeError("nenhum mesh para deformar")

    liquid = find_object("Liquid", "water")
    cap = find_object("Cap", "Tampa")
    label = find_object("Label", "ProjectedLabel")

    log(
        "fitting scales: "
        f"body=({args.body_width_scale:.3f},{args.body_depth_scale:.3f},"
        f"{args.height_scale:.3f}) cap_width={args.cap_width_scale:.3f}"
    )

    before_body_min, before_body_max = bbox_world(body)
    before_body_height = max(before_body_max.z - before_body_min.z, 1e-6)

    scale_mesh_world(
        body,
        args.body_width_scale,
        args.body_depth_scale,
        args.height_scale,
        anchor_bottom=True,
    )
    if liquid is not None:
        scale_mesh_world(
            liquid,
            args.body_width_scale * 0.96,
            args.body_depth_scale * 0.96,
            args.height_scale,
            anchor_bottom=True,
        )

    if label is not None:
        scale_mesh_world(
            label,
            max(0.70, args.body_width_scale * 0.92),
            1.0,
            max(0.80, args.height_scale * 0.95),
            anchor_bottom=False,
        )

    body_min, body_max = bbox_world(body)
    body_height = max(body_max.z - body_min.z, 1e-6)

    if cap is not None:
        base_cap_height_ratio = 0.16
        cap_height_scale = max(0.58, min(1.55, args.cap_height_ratio / base_cap_height_ratio))
        scale_mesh_world(
            cap,
            args.cap_width_scale,
            args.cap_width_scale,
            cap_height_scale,
            anchor_bottom=True,
        )
        cap_min, _cap_max = bbox_world(cap)
        overlap = body_height * 0.012
        translate_world(cap, Vector((0.0, 0.0, body_max.z - cap_min.z - overlap)))

    log(
        "body height: "
        f"before={before_body_height:.4f} after={body_height:.4f}"
    )


# ------------------------------------------------------------------ procedural silhouette


def material_principled(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float = 0.45,
    metallic: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    try:
        mat.blend_method = "BLEND"
    except (AttributeError, TypeError):
        pass

    bsdf = principled_bsdf(mat)
    if bsdf is None:
        return mat
    if bsdf.inputs.get("Base Color") is not None:
        bsdf.inputs["Base Color"].default_value = color
    if bsdf.inputs.get("Alpha") is not None:
        bsdf.inputs["Alpha"].default_value = color[3]
    if bsdf.inputs.get("Roughness") is not None:
        bsdf.inputs["Roughness"].default_value = roughness
    if bsdf.inputs.get("Metallic") is not None:
        bsdf.inputs["Metallic"].default_value = metallic
    if bsdf.inputs.get("Transmission Weight") is not None:
        bsdf.inputs["Transmission Weight"].default_value = 0.35
    return mat


def create_profile_mesh(
    name: str,
    profile_top_to_bottom: list[float],
    *,
    height: float,
    width: float,
    depth_ratio: float,
    z_offset: float,
    material: bpy.types.Material,
    segments: int = 24,
) -> bpy.types.Object:
    profile_bottom_to_top = list(reversed(profile_top_to_bottom))
    max_profile = max(max(profile_bottom_to_top), 1e-6)
    rings = len(profile_bottom_to_top)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for ring_index, raw_width in enumerate(profile_bottom_to_top):
        z = z_offset + (ring_index / max(rings - 1, 1)) * height
        normalized = max(0.10, raw_width / max_profile)
        half_x = width * normalized * 0.5
        half_y = max(width * depth_ratio * normalized * 0.5, width * 0.10)
        for segment in range(segments):
            theta = (segment / segments) * math.tau
            # Slightly flatter front/back, closer to a perfume bottle than a cylinder.
            vertices.append((half_x * math.cos(theta), half_y * math.sin(theta), z))

    bottom_center = len(vertices)
    vertices.append((0.0, 0.0, z_offset))
    top_center = len(vertices)
    vertices.append((0.0, 0.0, z_offset + height))

    for ring_index in range(rings - 1):
        base = ring_index * segments
        next_base = (ring_index + 1) * segments
        for segment in range(segments):
            a = base + segment
            b = base + (segment + 1) % segments
            c = next_base + (segment + 1) % segments
            d = next_base + segment
            faces.append((a, b, c, d))

    for segment in range(segments):
        faces.append((bottom_center, (segment + 1) % segments, segment))
        top_base = (rings - 1) * segments
        faces.append((top_center, top_base + segment, top_base + (segment + 1) % segments))

    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        bpy.ops.object.shade_smooth()
    except RuntimeError:
        pass
    obj.select_set(False)
    return obj


def create_frustum_box(
    name: str,
    *,
    bottom_width: float,
    top_width: float,
    depth: float,
    z_min: float,
    z_max: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    bw = bottom_width * 0.5
    tw = top_width * 0.5
    d = depth * 0.5
    vertices = [
        (-bw, -d, z_min), (bw, -d, z_min), (bw, d, z_min), (-bw, d, z_min),
        (-tw, -d, z_max), (tw, -d, z_max), (tw, d, z_max), (-tw, d, z_max),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bevel = obj.modifiers.new("SoftEdges", type="BEVEL")
    bevel.width = 0.035
    bevel.segments = 5
    obj.modifiers.new("WeightedNormals", type="WEIGHTED_NORMAL")
    return obj


def create_label_plane(
    label_path: Path,
    *,
    body_width: float,
    body_height: float,
    depth: float,
) -> None:
    if not label_path.exists():
        return
    mat = create_image_material("LabelMaterial", label_path)
    w = body_width * 0.56
    h = body_height * 0.36
    z = body_height * 0.48
    y = -(depth * 0.5) - 0.012
    vertices = [
        (-w / 2, y, z - h / 2),
        (w / 2, y, z - h / 2),
        (w / 2, y, z + h / 2),
        (-w / 2, y, z + h / 2),
    ]
    mesh = bpy.data.meshes.new("LabelPlaneMesh")
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new("Label", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    uv_layer = obj.data.uv_layers.new(name="LabelUV")
    for loop_index, uv in zip(obj.data.polygons[0].loop_indices, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv_layer.data[loop_index].uv = uv


def create_image_material(name: str, image_path: Path) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output = nodes.new(type="ShaderNodeOutputMaterial")
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    tex = nodes.new(type="ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(image_path), check_existing=True)
    try:
        tex.image.pack()
    except RuntimeError:
        pass
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def build_silhouette_model(args: argparse.Namespace) -> None:
    if args.fit_plan is None or not args.fit_plan.exists():
        raise FileNotFoundError(f"fit-plan nao encontrado: {args.fit_plan}")

    plan = json.loads(args.fit_plan.read_text(encoding="utf-8"))
    metrics = plan.get("metrics", {})
    profile = plan.get("profile_widths") or []
    if len(profile) < 8:
        aspect = float(metrics.get("aspect_ratio", 0.40))
        profile = [0.62, 0.62, 0.64, 0.70, 0.84, 0.95, 1.0, max(0.70, aspect * 2.0)]

    cap_ratio = max(0.18, min(float(plan.get("cap_height_ratio", 0.28)), 0.34))
    cap_count = max(3, min(len(profile) - 4, int(round(len(profile) * cap_ratio))))
    body_profile = profile[cap_count:]
    cap_profile = profile[:cap_count]

    clear_meshes()

    liquid_color = parse_color_hex(args.liquid_color or "#253D5E")
    glass_mat = material_principled("SmokyGlass", (0.05, 0.06, 0.06, 0.38), roughness=0.18)
    liquid_mat = material_principled(
        "BlueLiquid",
        (liquid_color[0], liquid_color[1], liquid_color[2], 0.58),
        roughness=0.28,
    )
    cap_mat = material_principled("BlackCap", (0.005, 0.005, 0.005, 1.0), roughness=0.30)

    body_height = 2.30
    cap_height = 0.86
    body_width = 1.02
    depth_ratio = 0.42

    create_profile_mesh(
        "Bottle",
        body_profile,
        height=body_height,
        width=body_width,
        depth_ratio=depth_ratio,
        z_offset=0.0,
        material=glass_mat,
    )

    liquid_profile = [max(0.20, width * 0.84) for width in body_profile[: max(4, int(len(body_profile) * 0.62))]]
    create_profile_mesh(
        "Liquid",
        liquid_profile,
        height=body_height * 0.62,
        width=body_width * 0.82,
        depth_ratio=depth_ratio * 0.92,
        z_offset=0.06,
        material=liquid_mat,
    )

    cap_bottom = max(cap_profile[-1], body_profile[0]) * body_width
    cap_top = max(cap_profile[0], cap_profile[min(len(cap_profile) - 1, 1)]) * body_width
    create_frustum_box(
        "Cap",
        bottom_width=max(cap_bottom, body_width * 0.58),
        top_width=max(cap_top, body_width * 0.52),
        depth=max(cap_bottom, cap_top) * 0.46,
        z_min=body_height - 0.02,
        z_max=body_height + cap_height,
        material=cap_mat,
    )

    if args.label_image is not None:
        create_label_plane(
            args.label_image,
            body_width=body_width,
            body_height=body_height,
            depth=body_width * depth_ratio,
        )

    log(
        "modelo procedural por silhueta criado: "
        f"profile={len(profile)} cap_ratio={cap_ratio:.2f}"
    )


def parse_color_hex(value: str) -> tuple[float, float, float, float]:
    raw = value.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"cor hex deve ter 6 digitos: {value}")
    return (
        int(raw[0:2], 16) / 255.0,
        int(raw[2:4], 16) / 255.0,
        int(raw[4:6], 16) / 255.0,
        1.0,
    )


def find_material(name: str) -> bpy.types.Material | None:
    expected = name.lower()
    for mat in bpy.data.materials:
        if base_name(mat.name).lower() == expected:
            return mat
    return None


def principled_bsdf(material: bpy.types.Material) -> bpy.types.Node | None:
    if not material.use_nodes:
        material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def apply_label_texture(image_path: Path) -> None:
    if not image_path.exists():
        raise FileNotFoundError(f"label nao encontrada: {image_path}")
    mat = find_material("LabelMaterial")
    if mat is None:
        log("AVISO: LabelMaterial ausente; label nao aplicada")
        return

    bsdf = principled_bsdf(mat)
    if bsdf is None:
        log("AVISO: LabelMaterial sem Principled BSDF")
        return

    image = bpy.data.images.load(str(image_path), check_existing=True)
    try:
        image.pack()
    except RuntimeError:
        pass

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    tex = nodes.new(type="ShaderNodeTexImage")
    tex.image = image
    tex.location = (bsdf.location.x - 350, bsdf.location.y)

    base_color = bsdf.inputs.get("Base Color")
    if base_color is not None:
        links.new(tex.outputs["Color"], base_color)
    alpha = bsdf.inputs.get("Alpha")
    if alpha is not None and "Alpha" in tex.outputs:
        links.new(tex.outputs["Alpha"], alpha)

    log(f"label aplicada: {image_path.name}")


def apply_liquid_color(value: str) -> None:
    mat = find_material("water")
    if mat is None:
        log("AVISO: material water ausente; cor nao aplicada")
        return
    bsdf = principled_bsdf(mat)
    if bsdf is None:
        return
    base_color = bsdf.inputs.get("Base Color")
    if base_color is not None:
        base_color.default_value = parse_color_hex(value)
        log(f"cor do liquido aplicada: {value}")


def normal_world(obj: bpy.types.Object, poly: bpy.types.MeshPolygon) -> Vector:
    mat3 = obj.matrix_world.to_3x3().inverted().transposed()
    normal = mat3 @ poly.normal
    return normal.normalized() if normal.length > 0 else UP_AXIS.copy()


def max_z(obj: bpy.types.Object) -> float:
    return bbox_world(obj)[1].z


def create_top_material(image_path: Path) -> bpy.types.Material:
    if not image_path.exists():
        raise FileNotFoundError(f"imagem do topo nao encontrada: {image_path}")
    for mat in list(bpy.data.materials):
        if base_name(mat.name) == "TopTextureMaterial":
            bpy.data.materials.remove(mat)

    image = bpy.data.images.load(str(image_path))
    try:
        image.pack()
    except RuntimeError:
        pass

    mat = bpy.data.materials.new("TopTextureMaterial")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (520, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (220, 60)
    tex = nodes.new(type="ShaderNodeTexImage")
    tex.location = (-120, 60)
    tex.image = image

    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def apply_top_texture(image_path: Path) -> None:
    cap = find_object("Cap", "Tampa")
    if cap is None:
        meshes = mesh_objects()
        if not meshes:
            return
        cap = max(meshes, key=max_z)

    faces = [p for p in cap.data.polygons if normal_world(cap, p).dot(UP_AXIS) >= 0.35]
    if not faces:
        faces = [p for p in cap.data.polygons if normal_world(cap, p).dot(UP_AXIS) >= 0.0]
    if not faces:
        log("AVISO: nenhuma face de topo encontrada")
        return

    world = cap.matrix_world
    vertices = cap.data.vertices
    xs: list[float] = []
    ys: list[float] = []
    for face in faces:
        for vertex_index in face.vertices:
            point = world @ vertices[vertex_index].co
            xs.append(point.x)
            ys.append(point.y)

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    uv_name = "TopProjectionUV"
    if uv_name in cap.data.uv_layers:
        cap.data.uv_layers.remove(cap.data.uv_layers[uv_name])
    uv_layer = cap.data.uv_layers.new(name=uv_name)
    cap.data.uv_layers.active = uv_layer

    face_indices = {face.index for face in faces}
    for face in cap.data.polygons:
        for loop_index, vertex_index in zip(face.loop_indices, face.vertices):
            if face.index not in face_indices:
                uv_layer.data[loop_index].uv = (0.0, 0.0)
                continue
            point = world @ vertices[vertex_index].co
            uv_layer.data[loop_index].uv = (
                (point.x - min_x) / span_x,
                (point.y - min_y) / span_y,
            )

    material = create_top_material(image_path)
    cap.data.materials.append(material)
    material_index = len(cap.data.materials) - 1
    for face in faces:
        face.material_index = material_index

    log(f"textura do topo aplicada em {len(faces)} faces")


def main() -> int:
    args = parse_args()
    log(f"template = {args.template}")
    log(f"output   = {args.output}")

    reset_scene()
    if args.fit_plan is not None:
        build_silhouette_model(args)
    else:
        import_template(args.template)
        fit_geometry(args)

        if args.label_image is not None:
            apply_label_texture(args.label_image)
        if args.top_image is not None:
            apply_top_texture(args.top_image)
        if args.liquid_color is not None:
            apply_liquid_color(args.liquid_color)

    export_glb(args.output)
    log("OK - template fitted")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
