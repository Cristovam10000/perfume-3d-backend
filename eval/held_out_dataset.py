"""Loader e validador do dataset held-out.

O dataset held-out vive em `back/eval_assets/held_out/` e é descrito por
um `manifest.json` (schema documentado no README desse diretório). Este
módulo:

1. Carrega o manifest, validando estrutura.
2. Resolve cada `file` para um `Path` absoluto que existe.
3. Devolve uma `HeldOutDataset` pronta para iteração pelo benchmark.

Também expõe `python -m eval.held_out_dataset --validate` para checar a
integridade do dataset sem rodar o benchmark inteiro.

Decisões de design:
- Validação **estrita**: se o manifest aponta para um arquivo inexistente
  ou tem id duplicado, levanta `HeldOutDatasetError`. Silenciar erros
  aqui poluiria o CSV final com NaNs incompreensíveis.
- Sem dependência de pydantic — `dataclasses` + checks manuais bastam
  para um schema pequeno e estável.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_VALID_SHAPE_CATEGORIES = frozenset(
    {"rectangular", "cylindrical", "ornamental", "round", "square"}
)

# Licenças aceitas. CC-BY-4.0 exige `source.author` no manifest.
_VALID_LICENSES = frozenset(
    {
        "CC0-1.0",
        "CC0",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC-BY",
        "PUBLIC-DOMAIN",
    }
)

# O dataset held-out vive em C:\TCC\TCC_eval_data\ por escolha do projeto
# (decisão: 2026-05-21). Por estar DENTRO da worktree IA, as worktrees
# Blander/Meshroom precisam apontar pra cá via env var TCC_EVAL_DATA_ROOT
# quando forem rodar benchmark — senão olhariam pra um diretório próprio
# inexistente. Em CI/Linux, basta setar TCC_EVAL_DATA_ROOT também.
_DEFAULT_EVAL_DATA_ROOT = Path(r"C:\TCC\TCC_eval_data")


def _resolve_held_out_dir() -> Path:
    env = os.environ.get("TCC_EVAL_DATA_ROOT")
    root = Path(env) if env else _DEFAULT_EVAL_DATA_ROOT
    return root / "held_out"


_DEFAULT_HELD_OUT_DIR = _resolve_held_out_dir()


class HeldOutDatasetError(Exception):
    """Falha ao carregar/validar o dataset held-out."""


@dataclass(frozen=True)
class HeldOutSource:
    """Metadados de proveniência de um modelo do held-out."""

    platform: str
    url: str
    license: str
    downloaded_at: str
    author: str | None = None


@dataclass(frozen=True)
class HeldOutModel:
    """Uma entrada validada do dataset.

    O `glb_path` é absoluto e já foi conferido (existe no disco).
    """

    id: str
    glb_path: Path
    shape_category: str
    source: HeldOutSource
    rotate_z_deg: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class HeldOutDataset:
    """Conjunto completo de modelos held-out, validado.

    Iterável: `for model in dataset: ...`
    Index por id: `dataset["perfume_001"]`
    Por categoria: `dataset.by_category("rectangular")`
    """

    root_dir: Path
    description: str
    created_at: str
    models: tuple[HeldOutModel, ...]

    def __iter__(self) -> Iterator[HeldOutModel]:
        return iter(self.models)

    def __len__(self) -> int:
        return len(self.models)

    def __getitem__(self, model_id: str) -> HeldOutModel:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"Modelo não encontrado: {model_id}")

    def by_category(self, category: str) -> tuple[HeldOutModel, ...]:
        return tuple(m for m in self.models if m.shape_category == category)


def load_held_out(
    held_out_dir: Path = _DEFAULT_HELD_OUT_DIR,
) -> HeldOutDataset:
    """Carrega e valida o dataset held-out a partir de seu diretório.

    Raises:
        FileNotFoundError: diretório ou manifest ausentes.
        HeldOutDatasetError: manifest inválido, arquivos faltando, etc.
    """
    if not held_out_dir.exists():
        raise FileNotFoundError(f"Diretório held-out não existe: {held_out_dir}")

    manifest_path = held_out_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json ausente em {held_out_dir}")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HeldOutDatasetError(f"manifest.json inválido: {exc}") from exc

    if not isinstance(raw, dict):
        raise HeldOutDatasetError("manifest.json deve ser um objeto JSON")
    if raw.get("version") != 1:
        raise HeldOutDatasetError(
            f"version esperada=1, recebida={raw.get('version')!r}"
        )

    raw_models = raw.get("models")
    if not isinstance(raw_models, list):
        raise HeldOutDatasetError("manifest.models deve ser uma lista")

    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    models: list[HeldOutModel] = []
    for i, entry in enumerate(raw_models):
        model = _parse_model_entry(entry, i, held_out_dir)
        if model.id in seen_ids:
            raise HeldOutDatasetError(f"id duplicado no manifest: {model.id!r}")
        if model.glb_path.name in seen_files:
            raise HeldOutDatasetError(
                f"arquivo duplicado no manifest: {model.glb_path.name!r}"
            )
        seen_ids.add(model.id)
        seen_files.add(model.glb_path.name)
        models.append(model)

    return HeldOutDataset(
        root_dir=held_out_dir,
        description=str(raw.get("description", "")),
        created_at=str(raw.get("created_at", "")),
        models=tuple(models),
    )


def _parse_model_entry(
    entry: object, index: int, held_out_dir: Path
) -> HeldOutModel:
    if not isinstance(entry, dict):
        raise HeldOutDatasetError(f"models[{index}] deve ser objeto JSON")

    def _require(key: str) -> object:
        if key not in entry:
            raise HeldOutDatasetError(f"models[{index}] sem campo obrigatório {key!r}")
        return entry[key]

    model_id = _require("id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise HeldOutDatasetError(f"models[{index}].id deve ser string não vazia")

    file_name = _require("file")
    if not isinstance(file_name, str) or not file_name.endswith(".glb"):
        raise HeldOutDatasetError(
            f"models[{index}].file deve terminar em .glb (recebido {file_name!r})"
        )
    glb_path = (held_out_dir / file_name).resolve()
    if not glb_path.exists():
        raise HeldOutDatasetError(
            f"models[{index}] aponta para arquivo inexistente: {glb_path}"
        )

    shape_category = _require("shape_category")
    if shape_category not in _VALID_SHAPE_CATEGORIES:
        raise HeldOutDatasetError(
            f"models[{index}].shape_category inválida: {shape_category!r}. "
            f"Esperado: {sorted(_VALID_SHAPE_CATEGORIES)}"
        )

    source_raw = _require("source")
    if not isinstance(source_raw, dict):
        raise HeldOutDatasetError(f"models[{index}].source deve ser objeto")
    source = _parse_source(source_raw, index)

    rotate_z = entry.get("rotate_z_deg", 0.0)
    if not isinstance(rotate_z, (int, float)):
        raise HeldOutDatasetError(
            f"models[{index}].rotate_z_deg deve ser numérico"
        )

    notes = entry.get("notes", "")
    if not isinstance(notes, str):
        raise HeldOutDatasetError(f"models[{index}].notes deve ser string")

    return HeldOutModel(
        id=model_id,
        glb_path=glb_path,
        shape_category=shape_category,
        source=source,
        rotate_z_deg=float(rotate_z),
        notes=notes,
    )


def _parse_source(raw: dict, index: int) -> HeldOutSource:
    for required in ("platform", "url", "license", "downloaded_at"):
        if required not in raw:
            raise HeldOutDatasetError(
                f"models[{index}].source sem campo {required!r}"
            )
    license_str = raw["license"]
    if license_str not in _VALID_LICENSES:
        raise HeldOutDatasetError(
            f"models[{index}].source.license inválida: {license_str!r}. "
            f"Aceitas: {sorted(_VALID_LICENSES)}"
        )
    author = raw.get("author")
    if license_str.startswith("CC-BY") and not author:
        raise HeldOutDatasetError(
            f"models[{index}] usa CC-BY mas não declara source.author "
            "(atribuição obrigatória)"
        )
    if author is not None and not isinstance(author, str):
        raise HeldOutDatasetError(
            f"models[{index}].source.author deve ser string"
        )
    return HeldOutSource(
        platform=str(raw["platform"]),
        url=str(raw["url"]),
        license=license_str,
        downloaded_at=str(raw["downloaded_at"]),
        author=author,
    )


# ------------------------------------------------------------------- CLI


def _main_validate(held_out_dir: Path) -> int:
    try:
        dataset = load_held_out(held_out_dir)
    except (FileNotFoundError, HeldOutDatasetError) as exc:
        print(f"[FALHA] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] {len(dataset)} modelos no manifest:")
    by_cat: dict[str, list[str]] = {}
    for m in dataset:
        by_cat.setdefault(m.shape_category, []).append(m.id)
    for cat, ids in sorted(by_cat.items()):
        print(f"  {cat:14s} ({len(ids)}): {', '.join(ids)}")

    # Aviso amigável quando o dataset ainda está vazio ou desbalanceado.
    if len(dataset) == 0:
        print(
            f"\n[AVISO] Dataset vazio. Veja {held_out_dir / 'README.md'}."
        )
    elif len(dataset) < 6:
        print(
            f"\n[AVISO] {len(dataset)} modelos é o mínimo para Wilcoxon pareado "
            "detectar efeito médio. Recomenda-se 10."
        )
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m eval.held_out_dataset",
        description="Valida o dataset held-out (manifest + arquivos GLB).",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="Valida o manifest e imprime sumário por categoria.",
    )
    p.add_argument(
        "--dir",
        type=Path,
        default=_DEFAULT_HELD_OUT_DIR,
        help=f"Diretório do dataset (default: {_DEFAULT_HELD_OUT_DIR})",
    )
    return p


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    if args.validate:
        sys.exit(_main_validate(args.dir))
    else:
        print("Use --validate", file=sys.stderr)
        sys.exit(2)
