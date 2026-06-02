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

    Vira uma linha do CSV final. `render_mode` identifica em qual condição
    de renderização o resultado foi medido (matte vs realistic).
    """

    model_id: str
    shape_category: str
    branch: str
    status: str  # "ok" | "error" | "timeout"
    duration_s: float
    error: str | None
    metrics: GeometricMetrics | None
    output_glb: Path | None
    render_mode: str = "matte"


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


def load_existing_ok_keys(csv_path: Path) -> set[tuple[str, str, str]]:
    """Lê o CSV existente e devolve as chaves `(model_id, branch, render_mode)`
    que já têm `status=ok`. Usado pelo `--skip-existing` para pular pares já
    completados com sucesso.

    Linhas com `status=error` NÃO são consideradas — entram pra re-tentar.
    """
    if not csv_path.exists():
        return set()
    keys: set[tuple[str, str, str]] = set()
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != _CSV_HEADER:
                return set()
            # Posições no header: model_id=0, branch=2, render_mode=3, status=4
            for row in reader:
                if len(row) < 5:
                    continue
                if row[4] == "ok":
                    keys.add((row[0], row[2], row[3]))
    except Exception:
        # CSV corrompido / inacessível — não pula nada por segurança
        return set()
    return keys


def benchmark_model(
    model: HeldOutModel,
    branches: dict[str, Path],
    eval_data_root: Path,
    blender_executable: Path,
    orbit_count: int = 24,
    render_mode: str = "matte",
    skip_keys: set[tuple[str, str, str]] | None = None,
) -> list[BranchResult]:
    """Para um modelo do dataset, roda todas as branches e mede métricas.

    Renderiza 4 cardeais + `orbit_count` vistas extras em órbita. As
    cardeais alimentam IA/Blander; as orbit (mais densas) alimentam
    Meshroom, que precisa de cobertura fotogramétrica.

    `render_mode` define se as imagens são renderizadas com materiais
    override (`matte`, geometria pura) ou originais + HDRI (`realistic`,
    simula condição real). Arquivos vão pra subpasta específica do modo
    pra permitir comparação entre os dois.
    """
    # Subpasta por modo: synthetic_views/<model>/<mode>/{*.png}
    # Arquivos de output por modo: outputs/<branch>/<model>__<mode>.glb
    views_dir = eval_data_root / "synthetic_views" / model.id / render_mode

    # 1. Render sintético — pula se já está completo (cardeais + orbit).
    cardinals_ok = all(
        (views_dir / f"{v}.png").exists() for v in ("front", "left", "back", "right")
    )
    orbit_ok = (
        orbit_count == 0
        or len(list(views_dir.glob("orbit_*.png"))) >= orbit_count
    )
    if not (cardinals_ok and orbit_ok):
        print(
            f"  ⏳ Renderizando (modo={render_mode}) "
            f"4 cardeais + {orbit_count} orbit...",
            file=sys.stderr,
            flush=True,
        )
        render_start = time.monotonic()
        render_synthetic_views(
            glb_path=model.glb_path,
            output_dir=views_dir,
            blender_executable=blender_executable,
            rotate_z_deg=model.rotate_z_deg,
            orbit_count=orbit_count,
            render_mode=render_mode,
        )
        print(
            f"  ✓ Render concluído em {time.monotonic() - render_start:.1f}s",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(f"  ↻ Render ({render_mode}) já em cache em {views_dir}", file=sys.stderr, flush=True)

    # 2. Para cada branch, invoca runner e mede métricas.
    # Sufixo __<mode> separa os GLBs gerados em cada modo de renderização.
    results: list[BranchResult] = []
    for branch_name, worktree in branches.items():
        # --skip-existing: pula se já temos linha ok no CSV pra esta chave.
        if skip_keys is not None and (model.id, branch_name, render_mode) in skip_keys:
            print(
                f"  ⏭ Branch {branch_name}: pulado (já existe row ok no CSV)",
                file=sys.stderr,
                flush=True,
            )
            continue

        output_glb = (
            eval_data_root / "outputs" / branch_name.lower()
            / f"{model.id}__{render_mode}.glb"
        )
        print(
            f"  ⏳ Branch {branch_name} processando...",
            file=sys.stderr,
            flush=True,
        )
        branch_start = time.monotonic()
        # Captura defensiva: se invoke_branch lançar exceção inesperada (subprocess
        # crashou de jeito esquisito, erro de I/O, etc), trata como error em vez de
        # propagar e matar o benchmark inteiro.
        try:
            payload = invoke_branch(
                branch=branch_name,
                worktree=worktree,
                views_dir=views_dir,
                output_glb=output_glb,
            )
        except Exception as exc:
            payload = {
                "status": "error",
                "error": f"invoke_branch crashou: {type(exc).__name__}: {exc}",
                "duration_s": time.monotonic() - branch_start,
            }
        elapsed = time.monotonic() - branch_start
        status_emoji = "✓" if payload.get("status") == "ok" else "✗"
        print(
            f"  {status_emoji} {branch_name}: {payload.get('status')} em {elapsed:.1f}s"
            + (f" — {payload.get('error', '')}" if payload.get("status") != "ok" else ""),
            file=sys.stderr,
            flush=True,
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
                    render_mode=render_mode,
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
                    render_mode=render_mode,
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
                    render_mode=render_mode,
                )
            )
    return results


# ---------------------------------------------------------------------- CSV


_CSV_HEADER = [
    "model_id",
    "shape_category",
    "branch",
    "render_mode",
    "status",
    "duration_s",
    "chamfer_l1",
    "chamfer_l2",
    "hausdorff",
    "f_score_001",
    "f_score_005",
    "error",
]


def write_csv(results: list[BranchResult], path: Path) -> None:
    """Faz UPSERT: preserva linhas anteriores, sobrescreve as que repetem
    (model_id, branch, render_mode). Assim rodar `--render-mode matte` e
    depois `--render-mode realistic` acumula linhas DIFERENTES (uma por
    modo) em vez de sobrescrever.

    A chave de identidade é o trio `(model_id, branch, render_mode)` — pra
    benchmark dual, o mesmo modelo aparece 2× por branch (uma linha por
    modo de render).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Lê linhas existentes (se houver) em dict por chave triple.
    existing: dict[tuple[str, str, str], list[str]] = {}
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header == _CSV_HEADER:
                for row in reader:
                    if len(row) >= 4:
                        existing[(row[0], row[2], row[3])] = row

    # Aplica os resultados novos por cima (upsert).
    for r in results:
        m = r.metrics
        row = [
            r.model_id,
            r.shape_category,
            r.branch,
            r.render_mode,
            r.status,
            f"{r.duration_s:.3f}",
            f"{m.chamfer_l1:.6f}" if m else "",
            f"{m.chamfer_l2:.6f}" if m else "",
            f"{m.hausdorff:.6f}" if m else "",
            f"{m.f_score_001:.4f}" if m else "",
            f"{m.f_score_005:.4f}" if m else "",
            r.error or "",
        ]
        existing[(r.model_id, r.branch, r.render_mode)] = row

    # Reescreve tudo, ordenado por (model_id, render_mode, branch).
    sorted_rows = sorted(existing.values(), key=lambda r: (r[0], r[3], r[2]))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_HEADER)
        for row in sorted_rows:
            writer.writerow(row)


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
    p.add_argument(
        "--orbit-count",
        type=int,
        default=24,
        help=(
            "Quantidade de vistas extras em órbita pra cada modelo, "
            "consumidas só pelo Meshroom (IA/Blander leem só as 4 cardeais). "
            "Default 24 = uma vista a cada ~15° de azimuth."
        ),
    )
    p.add_argument(
        "--render-mode",
        nargs="+",
        choices=("matte", "realistic"),
        default=["matte"],
        help=(
            "Modo(s) de renderização. Pode passar UM ou OS DOIS — para "
            "benchmark dual da metodologia C, use `--render-mode matte "
            "realistic` (roda os 2 sequencialmente, cada um popula sua "
            "subpasta e seu sufixo no CSV).\n"
            "  matte: materiais substituídos por diffuse opaco (geometria pura).\n"
            "  realistic: materiais originais + HDRI (simula app real)."
        ),
    )
    p.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="MODEL_ID",
        help=(
            "Filtra o dataset para rodar APENAS os model_ids listados. "
            "Útil pra debug incremental — testa 1 modelo, conserta, repete. "
            "Sem este flag, roda todos os modelos do manifest."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Roda no máximo N modelos (após o filtro --only). Útil pra smoke test.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Pula combinações (model_id, branch, render_mode) que já têm "
            "row com status=ok no CSV. Erros são re-tentados. Útil para "
            "retomar benchmark interrompido sem refazer trabalho."
        ),
    )
    args = p.parse_args()

    dataset = load_held_out(args.eval_data_root / "held_out")
    if len(dataset) == 0:
        print("Dataset vazio. Adicione modelos a manifest.json.", file=sys.stderr)
        return 1

    # Filtra dataset por --only / --limit (ordem importa: filtra, depois limita).
    models = list(dataset)
    if args.only:
        wanted = set(args.only)
        models = [m for m in models if m.id in wanted]
        missing = wanted - {m.id for m in models}
        if missing:
            print(f"--only não encontrou: {sorted(missing)}", file=sys.stderr)
            return 4
    if args.limit is not None and args.limit > 0:
        models = models[: args.limit]
    if not models:
        print("Nenhum modelo após aplicar --only/--limit.", file=sys.stderr)
        return 5

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

    # --skip-existing: carrega chaves já completadas com sucesso do CSV.
    skip_keys: set[tuple[str, str, str]] | None = None
    if args.skip_existing:
        skip_keys = load_existing_ok_keys(args.output)
        print(
            f"--skip-existing ativo: {len(skip_keys)} chaves (model, branch, mode) "
            f"já em ok no CSV serão puladas.",
            file=sys.stderr,
        )

    all_results: list[BranchResult] = []
    total_iters = len(models) * len(args.render_mode)
    iter_idx = 0
    for mode in args.render_mode:
        print(
            f"\n========== Iniciando render_mode={mode} ==========\n",
            file=sys.stderr,
        )
        for model in models:
            iter_idx += 1
            print(
                f"[{iter_idx}/{total_iters}] {model.id} ({model.shape_category}) "
                f"[{mode}]",
                file=sys.stderr,
            )
            model_results = benchmark_model(
                model=model,
                branches=branches,
                eval_data_root=args.eval_data_root,
                blender_executable=args.blender_executable,
                orbit_count=args.orbit_count,
                render_mode=mode,
                skip_keys=skip_keys,
            )
            all_results.extend(model_results)
            # Escrita INCREMENTAL: salva o CSV após cada (modelo, modo).
            # Garante que Ctrl+C / crash não perde resultados anteriores.
            # write_csv usa upsert por (model_id, branch, render_mode),
            # então é seguro escrever só os results desta iteração — os
            # anteriores ficam preservados no arquivo.
            try:
                write_csv(model_results, args.output)
                print(
                    f"  💾 CSV salvo (incremental) em {args.output}",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"  ⚠ Falha ao escrever CSV incremental: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    # Re-escreve no fim só por garantia (no-op se incremental funcionou).
    write_csv(all_results, args.output)
    print(f"CSV salvo em {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
