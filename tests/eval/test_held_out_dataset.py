from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.held_out_dataset import (
    _DEFAULT_HELD_OUT_DIR,
    HeldOutDataset,
    HeldOutDatasetError,
    HeldOutModel,
    HeldOutSource,
    load_held_out,
)


# ----------------------------------------------------------------- helpers


def _write_glb(path: Path) -> None:
    """Cria um arquivo GLB stub (8 bytes do magic, basta pra exists())."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF\x02\x00\x00\x00")


def _make_dataset_dir(
    tmp_path: Path,
    *,
    models: list[dict],
    version: int = 1,
    description: str = "test",
    created_at: str = "2026-05-18",
) -> Path:
    """Constrói um eval_assets/held_out/ válido com os GLBs e manifest."""
    root = tmp_path / "held_out"
    root.mkdir(parents=True, exist_ok=True)
    for m in models:
        if "file" in m:
            _write_glb(root / m["file"])
    manifest = {
        "version": version,
        "description": description,
        "created_at": created_at,
        "models": models,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return root


def _valid_entry(
    *,
    id: str = "perfume_001",
    file: str | None = None,
    shape_category: str = "rectangular",
    license: str = "CC0-1.0",
    author: str | None = None,
    rotate_z_deg: float = 0.0,
    notes: str = "",
) -> dict:
    src = {
        "platform": "sketchfab",
        "url": f"https://sketchfab.com/3d-models/{id}",
        "license": license,
        "downloaded_at": "2026-05-18",
    }
    if author:
        src["author"] = author
    entry: dict = {
        "id": id,
        "file": file or f"{id}.glb",
        "shape_category": shape_category,
        "source": src,
        "rotate_z_deg": rotate_z_deg,
    }
    if notes:
        entry["notes"] = notes
    return entry


# -------------------------------------------------------- success scenarios


class TestSuccessfulLoad:
    def test_loads_empty_dataset(self, tmp_path: Path):
        root = _make_dataset_dir(tmp_path, models=[])
        ds = load_held_out(root)
        assert isinstance(ds, HeldOutDataset)
        assert len(ds) == 0
        assert list(ds) == []

    def test_loads_single_cc0_model(self, tmp_path: Path):
        root = _make_dataset_dir(tmp_path, models=[_valid_entry()])
        ds = load_held_out(root)
        assert len(ds) == 1

        model = ds["perfume_001"]
        assert isinstance(model, HeldOutModel)
        assert model.id == "perfume_001"
        assert model.shape_category == "rectangular"
        assert model.glb_path.exists()
        assert model.glb_path.name == "perfume_001.glb"
        assert model.source.license == "CC0-1.0"
        assert model.source.author is None

    def test_loads_cc_by_requires_author(self, tmp_path: Path):
        entry = _valid_entry(license="CC-BY-4.0", author="Author Name")
        root = _make_dataset_dir(tmp_path, models=[entry])
        ds = load_held_out(root)
        assert ds["perfume_001"].source.author == "Author Name"

    def test_iter_returns_all_models(self, tmp_path: Path):
        entries = [
            _valid_entry(id="p1", shape_category="rectangular"),
            _valid_entry(id="p2", shape_category="cylindrical"),
            _valid_entry(id="p3", shape_category="round"),
        ]
        root = _make_dataset_dir(tmp_path, models=entries)
        ds = load_held_out(root)
        ids = [m.id for m in ds]
        assert ids == ["p1", "p2", "p3"]

    def test_by_category_filters(self, tmp_path: Path):
        entries = [
            _valid_entry(id="r1", shape_category="rectangular"),
            _valid_entry(id="r2", shape_category="rectangular"),
            _valid_entry(id="c1", shape_category="cylindrical"),
        ]
        root = _make_dataset_dir(tmp_path, models=entries)
        ds = load_held_out(root)
        rect = ds.by_category("rectangular")
        assert {m.id for m in rect} == {"r1", "r2"}
        assert len(ds.by_category("ornamental")) == 0

    def test_rotate_z_deg_preserved(self, tmp_path: Path):
        entry = _valid_entry(rotate_z_deg=-90.0)
        root = _make_dataset_dir(tmp_path, models=[entry])
        ds = load_held_out(root)
        assert ds["perfume_001"].rotate_z_deg == -90.0


# ---------------------------------------------------------- file-level errors


class TestDirectoryErrors:
    def test_missing_directory(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Diretório"):
            load_held_out(tmp_path / "ghost")

    def test_missing_manifest(self, tmp_path: Path):
        (tmp_path / "held_out").mkdir()
        with pytest.raises(FileNotFoundError, match="manifest.json"):
            load_held_out(tmp_path / "held_out")

    def test_invalid_json(self, tmp_path: Path):
        root = tmp_path / "held_out"
        root.mkdir()
        (root / "manifest.json").write_text("{not json")
        with pytest.raises(HeldOutDatasetError, match="inválido"):
            load_held_out(root)


# --------------------------------------------------------- schema errors


class TestSchemaValidation:
    def test_wrong_version(self, tmp_path: Path):
        root = _make_dataset_dir(tmp_path, models=[], version=2)
        with pytest.raises(HeldOutDatasetError, match="version"):
            load_held_out(root)

    def test_models_not_a_list(self, tmp_path: Path):
        root = tmp_path / "held_out"
        root.mkdir()
        (root / "manifest.json").write_text(
            json.dumps({"version": 1, "models": "nope"})
        )
        with pytest.raises(HeldOutDatasetError, match="lista"):
            load_held_out(root)

    def test_missing_id(self, tmp_path: Path):
        entry = _valid_entry()
        del entry["id"]
        root = _make_dataset_dir(tmp_path, models=[entry])
        with pytest.raises(HeldOutDatasetError, match="'id'"):
            load_held_out(root)

    def test_empty_id(self, tmp_path: Path):
        entry = _valid_entry(id="")
        root = _make_dataset_dir(tmp_path, models=[entry])
        with pytest.raises(HeldOutDatasetError, match="id"):
            load_held_out(root)

    def test_invalid_shape_category(self, tmp_path: Path):
        entry = _valid_entry(shape_category="triangular")
        root = _make_dataset_dir(tmp_path, models=[entry])
        with pytest.raises(HeldOutDatasetError, match="shape_category"):
            load_held_out(root)

    def test_file_must_end_in_glb(self, tmp_path: Path):
        entry = _valid_entry(file="perfume.obj")
        # Não deixa _write_glb criar o arquivo .obj
        root = tmp_path / "held_out"
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(
            json.dumps({"version": 1, "models": [entry]})
        )
        with pytest.raises(HeldOutDatasetError, match=".glb"):
            load_held_out(root)

    def test_glb_file_must_exist(self, tmp_path: Path):
        entry = _valid_entry()
        # Cria o manifest mas NÃO o GLB
        root = tmp_path / "held_out"
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(
            json.dumps({"version": 1, "models": [entry]})
        )
        with pytest.raises(HeldOutDatasetError, match="arquivo inexistente"):
            load_held_out(root)

    def test_duplicate_id_rejected(self, tmp_path: Path):
        entries = [
            _valid_entry(id="dup", file="a.glb"),
            _valid_entry(id="dup", file="b.glb"),
        ]
        root = _make_dataset_dir(tmp_path, models=entries)
        with pytest.raises(HeldOutDatasetError, match="duplicado"):
            load_held_out(root)

    def test_duplicate_file_rejected(self, tmp_path: Path):
        entries = [
            _valid_entry(id="a", file="same.glb"),
            _valid_entry(id="b", file="same.glb"),
        ]
        root = _make_dataset_dir(tmp_path, models=entries)
        with pytest.raises(HeldOutDatasetError, match="duplicado"):
            load_held_out(root)


# ------------------------------------------------------ license validation


class TestLicenseValidation:
    def test_unknown_license_rejected(self, tmp_path: Path):
        entry = _valid_entry(license="ARR")
        root = _make_dataset_dir(tmp_path, models=[entry])
        with pytest.raises(HeldOutDatasetError, match="license"):
            load_held_out(root)

    def test_cc_by_without_author_rejected(self, tmp_path: Path):
        entry = _valid_entry(license="CC-BY-4.0")  # sem author
        root = _make_dataset_dir(tmp_path, models=[entry])
        with pytest.raises(HeldOutDatasetError, match="author"):
            load_held_out(root)

    def test_cc0_without_author_ok(self, tmp_path: Path):
        entry = _valid_entry(license="CC0-1.0")  # sem author
        root = _make_dataset_dir(tmp_path, models=[entry])
        ds = load_held_out(root)
        assert ds["perfume_001"].source.author is None


# --------------------------------------------------------- real manifest


class TestRealManifest:
    """Sanity check do manifest.json real do projeto.

    Carrega o dataset apontado por TCC_EVAL_DATA_ROOT (ou o default
    C:\\TCC_eval_data\\held_out\\). Skip se o diretório não existe ainda —
    máquinas de CI ou de outros desenvolvedores não têm o dataset.
    """

    def test_real_manifest_loads(self):
        root = _DEFAULT_HELD_OUT_DIR
        if not root.exists():
            pytest.skip(f"Held-out real não existe em {root}")
        ds = load_held_out(root)
        # Pode estar vazio (dataset ainda em curadoria), mas deve carregar sem erro.
        assert isinstance(ds, HeldOutDataset)

    def test_env_var_overrides_default(self, monkeypatch, tmp_path: Path):
        """TCC_EVAL_DATA_ROOT deve mudar para onde o loader olha por default."""
        from eval.held_out_dataset import _resolve_held_out_dir

        monkeypatch.setenv("TCC_EVAL_DATA_ROOT", str(tmp_path))
        resolved = _resolve_held_out_dir()
        assert resolved == tmp_path / "held_out"

    def test_env_var_absent_uses_default(self, monkeypatch):
        from eval.held_out_dataset import (
            _DEFAULT_EVAL_DATA_ROOT,
            _resolve_held_out_dir,
        )

        monkeypatch.delenv("TCC_EVAL_DATA_ROOT", raising=False)
        resolved = _resolve_held_out_dir()
        assert resolved == _DEFAULT_EVAL_DATA_ROOT / "held_out"
