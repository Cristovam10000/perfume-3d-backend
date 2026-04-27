"""Lê os .gltf de raw/ e imprime estrutura (nodes, meshes, materiais).

Não usa Blender — só parseia JSON. Útil pra decidir a estratégia de
normalização antes de escrever o script Blender específico.

Uso:
    python scripts/blender/inspect_raw_templates.py
"""

from __future__ import annotations

import json
from pathlib import Path

BACK_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = BACK_ROOT / "assets" / "templates" / "raw"


def find_gltfs() -> list[Path]:
    return sorted(RAW_DIR.rglob("scene.gltf"))


def inspect(path: Path) -> None:
    rel = path.relative_to(RAW_DIR)
    print(f"\n=== {rel} ===")
    try:
        gltf = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  erro lendo: {exc}")
        return

    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    materials = gltf.get("materials", [])
    images = gltf.get("images", [])
    textures = gltf.get("textures", [])

    print(f"  nodes:     {len(nodes)}")
    print(f"  meshes:    {len(meshes)}")
    print(f"  materials: {len(materials)} -> {[m.get('name') for m in materials]}")
    print(f"  images:    {len(images)} -> {[i.get('name') or i.get('uri') for i in images]}")
    print(f"  textures:  {len(textures)}")

    # Lista meshes que cada node usa, com o material primário
    print("  mesh nodes:")
    for n in nodes:
        if "mesh" in n:
            mesh_idx = n["mesh"]
            mesh = meshes[mesh_idx] if mesh_idx < len(meshes) else {}
            prims = mesh.get("primitives", [])
            mat_indices = [p.get("material") for p in prims if p.get("material") is not None]
            mat_names = [
                materials[i].get("name", f"#{i}") if i is not None and i < len(materials) else "?"
                for i in mat_indices
            ]
            mesh_name = mesh.get("name", "?")
            print(f"    '{n.get('name')}' -> mesh[{mesh_idx}] '{mesh_name}' mat={mat_names}")


if __name__ == "__main__":
    paths = find_gltfs()
    print(f"Encontrados {len(paths)} templates raw")
    for p in paths:
        inspect(p)
