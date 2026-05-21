"""Orquestrador do benchmark: dataset × branches × métricas → CSV.

Vive na branch `IA` mas chama o `run_benchmark.py` de cada worktree
(Blander/Meshroom/IA) via subprocess. Resultado: uma linha CSV por
(model_id, branch) com tempo, métricas geométricas e status.

Fluxo de uma linha:
    1. Renderiza 4 vistas cardeais do GLB ground-truth (synthetic_dataset)
    2. Para cada branch:
       a. Invoca worktree/back/run_benchmark.py com --views-dir + --output-glb
       b. Recebe JSON {status, glb, duration_s} do stdout
       c. Carrega o GLB resultante
       d. Computa Chamfer/Hausdorff/F-Score contra o GT
    3. Escreve linha no CSV

Estado: **esqueleto**. Funções de I/O e orquestração estão prontas; falta
plugar os runners reais quando as worktrees Blander/Meshroom existirem
e tiverem seus próprios `run_benchmark.py`.

Uso (quando completo):

    python -m eval.benchmark \\
        --dataset held_out \\
        --branches IA Blander Meshroom \\
        --output  C:/TCC_eval_data/results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from eval.held_out_dataset import HeldOutModel, load_held_out
from eval.metrics.geometric import GeometricMetrics, compute_all
from eval.synthetic_dataset import render_synthetic_views

# Caminhos default — assumem o layout descrito em WORKTREE_SETUP.md.
# Dataset vive dentro da worktree IA por decisão do projeto (2026-05-21).
_DEFAULT_EVAL_DATA_ROOT = Path(r"C:\TCC\TCC_eval_data")
# O repositório git é o `back/` (não há nesting com `back/` dentro da worktree).
# Por isso a worktree IA atual é C:\TCC\back\, e Blander/Meshroom serão criadas
# como worktrees siblings em caminhos top-level.
_DEFAULT_WORKTREES = {
    "IA": Path(r"C:\TCC\back"),
    "Blander": Path(r"C:\TCC_blander"),
    "Meshroom": Path(r"C:\TCC_meshroom"),
}


# ----------------------------------------------------------------- dataclasses


@dataclass
class BranchResult:
    """Resultado de uma branch em um modelo do dataset.

    Vira uma linha do CSV final.
    """

    model_id: str
    shape_category: str
    branch: str
    status: str  # "ok" | "error" | "timeout"
    duration_s: float
    error: str | None
    metrics: GeometricMetrics | None
    output_glb: Path | None


# ------------------------------------------------------------------ runners


def invoke_branch(
    branch: str,
    worktree: Path,
    views_dir: Path,
    output_glb: Path,
    timeout_s: float = 1800.0,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Chama o `run_benchmark.py` da worktree daquela branch via subprocess.

    Retorna o JSON parseado do stdout (uma linha). Em caso de erro de
    subprocess, devolve um dict no formato esperado pelo CSV.
    """
    python_exe = worktree / ".venv" / "Scripts" / "python.exe"
    script = worktree / "run_benchmark.py"

    if not python_exe.exists():
        return {
            "status": "error",
            "error": f"venv não encontrado em {python_exe}",
            "duration_s": 0.0,
        }
    if not script.exists():
        return {
            "status": "error",
            "error": f"run_benchmark.py não existe em {script}",
            "duration_s": 0.0,
        }

    cmd = [
        str(python_exe),
        str(script),
        "--views-dir",
        str(views_dir),
        "--output-glb",
        str(output_glb),
    ]
    # Cache desabilitado durante benchmark — runs idênticos não podem se
    # auto-canibalizar via cache CLIP.
    env_overrides = {"CACHE_ENABLED": "false"}
    if extra_env:
        env_overrides.update(extra_env)

    import os

    env = os.environ.copy()
    env.update(env_overrides)

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(worktree),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"timeout após {timeout_s}s",
            "duration_s": time.monotonic() - start,
        }

    # Pega a ÚLTIMA linha JSON do stdout (compat com logs de progresso).
    payload = _parse_last_json_line(result.stdout)
    if payload is None:
        return {
            "status": "error",
            "error": (
                f"stdout inválido (exit={result.returncode}). "
                f"stderr (500c): {result.stderr[-500:]!r}"
            ),
            "duration_s": time.monotonic() - start,
        }
    return payload


def _parse_last_json_line(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


# -------------------------------------------------------------- main pipeline


def benchmark_model(
    model: HeldOutModel,
    branches: dict[str, Path],
    eval_data_root: Path,
    blender_executable: Path,
) -> list[BranchResult]:
    """Para um modelo do dataset, roda todas as branches e mede métricas."""
    views_dir = eval_data_root / "synthetic_views" / model.id

    # 1. Render sintético (gera 4 vistas do GT) — pula se já existe.
    if not all((views_dir / f"{v}.png").exists() for v in ("front", "left", "back", "right")):
        render_synthetic_views(
            glb_path=model.glb_path,
            output_dir=views_dir,
            blender_executable=blender_executable,
            rotate_z_deg=model.rotate_z_deg,
        )

    # 2. Para cada branch, invoca runner e mede métricas
    results: list[BranchResult] = []
    for branch_name, worktree in branches.items():
        output_glb = eval_data_root / "outputs" / branch_name.lower() / f"{model.id}.glb"
        payload = invoke_branch(
            branch=branch_name,
            worktree=worktree,
            views_dir=views_dir,
            output_glb=output_glb,
        )

        if payload["status"] != "ok":
            results.append(
                BranchResult(
                    model_id=model.id,
                    shape_category=model.shape_category,
                    branch=branch_name,
                    status=payload["status"],
                    duration_s=float(payload.get("duration_s", 0.0)),
                    error=payload.get("error"),
                    metrics=None,
                    output_glb=None,
                )
            )
            continue

        # Calcula métricas — pode falhar se o GLB de saída está corrompido.
        try:
            metrics = compute_all(pred=output_glb, gt=model.glb_path)
            results.append(
                BranchResult(
                    model_id=model.id,
                    shape_category=model.shape_category,
                    branch=branch_name,
                    status="ok",
                    duration_s=float(payload["duration_s"]),
                    error=None,
                    metrics=metrics,
                    output_glb=output_glb,
                )
            )
        except Exception as exc:
            results.append(
                BranchResult(
                    model_id=model.id,
                    shape_category=model.shape_category,
                    branch=branch_name,
                    status="error",
                    duration_s=float(payload["duration_s"]),
                    error=f"metrics failed: {exc}",
                    metrics=None,
                    output_glb=output_glb,
                )
            )
    return results


# ---------------------------------------------------------------------- CSV


def write_csv(results: list[BranchResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "model_id",
                "shape_category",
                "branch",
                "status",
                "duration_s",
                "chamfer_l1",
                "chamfer_l2",
                "hausdorff",
                "f_score_001",
                "f_score_005",
                "error",
            ]
        )
        for r in results:
            m = r.metrics
            writer.writerow(
                [
                    r.model_id,
                    r.shape_category,
                    r.branch,
                    r.status,
                    f"{r.duration_s:.3f}",
                    f"{m.chamfer_l1:.6f}" if m else "",
                    f"{m.chamfer_l2:.6f}" if m else "",
                    f"{m.hausdorff:.6f}" if m else "",
                    f"{m.f_score_001:.4f}" if m else "",
                    f"{m.f_score_005:.4f}" if m else "",
                    r.error or "",
                ]
            )


# ----------------------------------------------------------------------- CLI


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m eval.benchmark",
        description="Orquestra dataset × branches × métricas e salva CSV.",
    )
    p.add_argument(
        "--dataset",
        choices=["held_out"],
        default="held_out",
        help="Dataset a usar.",
    )
    p.add_argument(
        "--branches",
        nargs="+",
        default=["IA"],
        help="Branches a avaliar (devem ter worktree).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_EVAL_DATA_ROOT / "results.csv",
        help="CSV de saída.",
    )
    p.add_argument(
        "--eval-data-root",
        type=Path,
        default=_DEFAULT_EVAL_DATA_ROOT,
        help="Raiz dos dados de eval (held_out, synthetic_views, outputs).",
    )
    p.add_argument(
        "--blender-executable",
        type=Path,
        default=Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
    )
    args = p.parse_args()

    dataset = load_held_out(args.eval_data_root / "held_out")
    if len(dataset) == 0:
        print("Dataset vazio. Adicione modelos a manifest.json.", file=sys.stderr)
        return 1

    branches: dict[str, Path] = {}
    for name in args.branches:
        if name not in _DEFAULT_WORKTREES:
            print(f"Branch desconhecida: {name}", file=sys.stderr)
            return 2
        worktree = _DEFAULT_WORKTREES[name]
        if not worktree.exists():
            print(
                f"Worktree não existe: {worktree}. "
                f"Crie com `git worktree add {worktree} {name}`",
                file=sys.stderr,
            )
            return 3
        branches[name] = worktree

    all_results: list[BranchResult] = []
    for i, model in enumerate(dataset, 1):
        print(
            f"[{i}/{len(dataset)}] {model.id} ({model.shape_category})",
            file=sys.stderr,
        )
        all_results.extend(
            benchmark_model(
                model=model,
                branches=branches,
                eval_data_root=args.eval_data_root,
                blender_executable=args.blender_executable,
            )
        )

    write_csv(all_results, args.output)
    print(f"CSV salvo em {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
