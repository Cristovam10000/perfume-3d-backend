"""Valida que os templates GLB normalizados em `assets/templates/normalized/`
estão íntegros e seguem a convenção exigida pelo TemplateProcessor.

Convenção:
- GLB válido (magic 'glTF', versão 2)
- Pelo menos os nós obrigatórios `Bottle`, `Cap` e `Label` presentes
- `Liquid` é opcional mas recomendado
- `LabelMaterial` existe (será substituído em runtime pelo material do produto)
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

BACK_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BACK_ROOT / "assets" / "templates" / "normalized"

REQUIRED_NODES = {"Bottle", "Label"}
# `Cap` e `Liquid` sao opcionais — alguns templates do Sketchfab vem como
# uma peca unica (frasco + tampa moldados juntos) e nao da pra separar.
OPTIONAL_NODES = {"Cap", "Liquid"}
REQUIRED_MATERIALS = {"LabelMaterial"}


def _parse_glb(path: Path) -> dict:
    """Extrai e parseia o chunk JSON de um arquivo GLB."""
    data = path.read_bytes()
    assert len(data) >= 20, f"GLB muito curto: {path}"
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "Magic header não é 'glTF'"
    assert version == 2, f"Versão glTF inesperada: {version}"
    assert total_length == len(data), "Length do header não bate"

    json_chunk_length, json_chunk_type = struct.unpack_from("<II", data, 12)
    assert json_chunk_type == 0x4E4F534A, "Primeiro chunk deveria ser JSON"

    json_bytes = data[20 : 20 + json_chunk_length].decode("utf-8").rstrip()
    return json.loads(json_bytes)


def _glb_files() -> list[Path]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(TEMPLATES_DIR.glob("*.glb"))


class TestNormalizedTemplates:
    def test_at_least_one_normalized_template_exists(self):
        files = _glb_files()
        assert files, (
            f"Nenhum template normalizado encontrado em {TEMPLATES_DIR}. "
            "Rode `scripts/blender/normalize_*.py` via Blender headless."
        )

    @pytest.mark.parametrize("glb", _glb_files() or [None], ids=lambda p: p.name if p else "no-templates")
    def test_template_is_valid_glb(self, glb: Path | None):
        if glb is None:
            pytest.skip("Sem templates pra validar")
        gltf = _parse_glb(glb)
        assert "asset" in gltf
        assert gltf["asset"].get("version") == "2.0"

    @pytest.mark.parametrize("glb", _glb_files() or [None], ids=lambda p: p.name if p else "no-templates")
    def test_required_nodes_present(self, glb: Path | None):
        if glb is None:
            pytest.skip("Sem templates pra validar")
        gltf = _parse_glb(glb)
        node_names = {n.get("name") for n in gltf.get("nodes", [])}
        missing = REQUIRED_NODES - node_names
        assert not missing, (
            f"{glb.name} sem nós obrigatórios: {missing}. "
            f"Presentes: {sorted(node_names)}"
        )

    @pytest.mark.parametrize("glb", _glb_files() or [None], ids=lambda p: p.name if p else "no-templates")
    def test_required_materials_present(self, glb: Path | None):
        if glb is None:
            pytest.skip("Sem templates pra validar")
        gltf = _parse_glb(glb)
        mat_names = {m.get("name") for m in gltf.get("materials", [])}
        missing = REQUIRED_MATERIALS - mat_names
        assert not missing, (
            f"{glb.name} sem materiais obrigatórios: {missing}. "
            f"Presentes: {sorted(mat_names)}"
        )

    @pytest.mark.parametrize("glb", _glb_files() or [None], ids=lambda p: p.name if p else "no-templates")
    def test_each_required_node_has_a_mesh(self, glb: Path | None):
        if glb is None:
            pytest.skip("Sem templates pra validar")
        gltf = _parse_glb(glb)
        nodes_by_name = {n.get("name"): n for n in gltf.get("nodes", [])}
        for required in REQUIRED_NODES:
            node = nodes_by_name.get(required)
            assert node is not None, f"{glb.name}: nó '{required}' ausente"
            assert "mesh" in node, f"{glb.name}: nó '{required}' não referencia mesh"
