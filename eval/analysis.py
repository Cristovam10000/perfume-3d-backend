"""Análise dos resultados do benchmark: tabelas, Wilcoxon e gráficos.

Lê o `results.csv` (3 métodos × N modelos × 2 modos de render) e gera, em
segundos, os artefatos prontos para a monografia / pré-projeto:

  - **Tabelas** de médias por método (matte e realistic) → stdout + `analysis_summary.md`
  - **Wilcoxon** pareado IA × Blander (por modo, por métrica) → p-valor de significância
  - **3 gráficos PNG**:
      01_taxa_sucesso.png        — barras de taxa de sucesso por método
      02_boxplot_fscore_matte.png — distribuição do F-Score@1% (IA × Blander)
      03_tempo_vs_qualidade.png   — dispersão tempo × qualidade (trade-off)

É análise pura sobre o CSV: não roda Blender/Hunyuan/Meshroom, não usa GPU.

Uso:
    python -m eval.analysis [--csv PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")  # backend sem display (gera PNG direto)
import matplotlib.pyplot as plt  # noqa: E402
from scipy.stats import wilcoxon  # noqa: E402

# Console do Windows usa cp1252 por padrão e quebra ao imprimir ↑/↓.
# Forçamos UTF-8 no stdout (o arquivo .md já é gravado em UTF-8 à parte).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_DEFAULT_CSV = Path(r"C:\TCC\TCC_eval_data\results.csv")
_DEFAULT_OUT = Path(r"C:\TCC\TCC_eval_data\analysis")

# Métricas e direção (True = maior é melhor).
METRICS = ["chamfer_l1", "chamfer_l2", "hausdorff", "f_score_001", "f_score_005"]
HIGHER_BETTER = {
    "chamfer_l1": False,
    "chamfer_l2": False,
    "hausdorff": False,
    "f_score_001": True,
    "f_score_005": True,
}
METRIC_LABEL = {
    "chamfer_l1": "Chamfer L1 ↓",
    "chamfer_l2": "Chamfer L2 ↓",
    "hausdorff": "Hausdorff ↓",
    "f_score_001": "F-Score@1% ↑",
    "f_score_005": "F-Score@5% ↑",
}
BRANCH_ORDER = ["IA", "Blander", "Meshroom"]
BRANCH_COLOR = {"IA": "#2E7D32", "Blander": "#1565C0", "Meshroom": "#B71C1C"}
MODES = ["matte", "realistic"]


# --------------------------------------------------------------------- helpers


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ok_values(rows, branch, mode, metric) -> list[float]:
    out = []
    for r in rows:
        if r["branch"] != branch or r["render_mode"] != mode or r["status"] != "ok":
            continue
        v = to_float(r.get(metric))
        if v is not None:
            out.append(v)
    return out


# ----------------------------------------------------------------- 1. tabelas


def success_counts(rows) -> dict[str, list[int]]:
    """branch -> [ok, total] sobre todas as linhas (todos os modos)."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        counts[r["branch"]][1] += 1
        if r["status"] == "ok":
            counts[r["branch"]][0] += 1
    return counts


def mean_table_md(rows, mode) -> str:
    """Tabela markdown de médias (± desvio) por método, para um modo."""
    branches = [b for b in BRANCH_ORDER if any(
        r["branch"] == b and r["render_mode"] == mode and r["status"] == "ok"
        for r in rows
    )]
    header = "| Método | n | " + " | ".join(METRIC_LABEL[m] for m in METRICS) + " |"
    sep = "|" + "---|" * (len(METRICS) + 2)
    lines = [header, sep]
    for b in branches:
        cells = []
        n = 0
        for m in METRICS:
            vals = ok_values(rows, b, mode, m)
            n = max(n, len(vals))
            if vals:
                cells.append(f"{np.mean(vals):.4f} ± {np.std(vals):.4f}")
            else:
                cells.append("—")
        lines.append(f"| {b} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------- 2. Wilcoxon


def paired_ia_blander(rows, mode, metric):
    """Pares (IA, Blander) por modelo onde AMBOS deram ok no mesmo modo."""
    by_model: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        if r["render_mode"] != mode or r["status"] != "ok":
            continue
        v = to_float(r.get(metric))
        if v is not None:
            by_model[r["model_id"]][r["branch"]] = v
    ia, bl = [], []
    for d in by_model.values():
        if "IA" in d and "Blander" in d:
            ia.append(d["IA"])
            bl.append(d["Blander"])
    return np.array(ia), np.array(bl)


def wilcoxon_md(rows) -> str:
    lines = ["| Modo | Métrica | n pares | mediana IA | mediana Blander | p-valor | significativo? |",
             "|---|---|---|---|---|---|---|"]
    for mode in MODES:
        for metric in ("chamfer_l1", "f_score_001"):
            ia, bl = paired_ia_blander(rows, mode, metric)
            n = len(ia)
            if n < 1:
                continue
            med_ia, med_bl = float(np.median(ia)), float(np.median(bl))
            try:
                stat, p = wilcoxon(ia, bl)
                p_str = f"{p:.4g}"
                sig = "sim (p<0,05)" if p < 0.05 else "não"
            except ValueError as exc:
                p_str = f"n/d ({exc})"
                sig = "—"
            lines.append(
                f"| {mode} | {METRIC_LABEL[metric]} | {n} | {med_ia:.4f} | "
                f"{med_bl:.4f} | {p_str} | {sig} |"
            )
    return "\n".join(lines)


# ----------------------------------------------------------------- 3. gráficos


def plot_success(counts, out: Path) -> Path:
    branches = [b for b in BRANCH_ORDER if b in counts]
    rates = [100 * counts[b][0] / counts[b][1] if counts[b][1] else 0 for b in branches]
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(branches, rates, color=[BRANCH_COLOR[b] for b in branches])
    for b, bar in zip(branches, bars):
        ok, tot = counts[b]
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{ok}/{tot}\n({100*ok/tot:.0f}%)" if tot else "0",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Taxa de sucesso (%)")
    ax.set_ylim(0, 109)
    ax.set_title("Taxa de sucesso por método (todos os modelos × modos)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    path = out / "01_taxa_sucesso.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_boxplot(rows, out: Path, metric="f_score_001", mode="matte") -> Path:
    data, labels, colors = [], [], []
    for b in ("IA", "Blander"):  # Meshroom não tem valores (0% sucesso)
        vals = ok_values(rows, b, mode, metric)
        if vals:
            data.append(vals)
            labels.append(b)
            colors.append(BRANCH_COLOR[b])
    fig, ax = plt.subplots(figsize=(6, 4))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, showmeans=True)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.55)
    ax.set_ylabel(METRIC_LABEL[metric])
    ax.set_title(f"Distribuição do {METRIC_LABEL[metric]} — modo {mode}\n"
                 f"(Meshroom omitido: 0% de sucesso, sem métricas)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    path = out / f"02_boxplot_{metric}_{mode}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_scatter(rows, out: Path, metric="f_score_001") -> Path:
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for b in ("IA", "Blander"):  # Meshroom sem métrica
        xs, ys = [], []
        for r in rows:
            if r["branch"] != b or r["status"] != "ok":
                continue
            d = to_float(r.get("duration_s"))
            v = to_float(r.get(metric))
            if d is not None and v is not None and d > 0:
                xs.append(d)
                ys.append(v)
        if xs:
            ax.scatter(xs, ys, label=b, color=BRANCH_COLOR[b], alpha=0.7, s=45,
                       edgecolors="white", linewidths=0.5)
    ax.set_xscale("log")
    ax.set_xlabel("Tempo por modelo (s, escala log)")
    ax.set_ylabel(METRIC_LABEL[metric])
    ax.set_title("Trade-off tempo × qualidade")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = out / "03_tempo_vs_qualidade.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------- main


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m eval.analysis")
    p.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = p.parse_args()

    if not args.csv.exists():
        print(f"CSV não encontrado: {args.csv}")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    rows = load_rows(args.csv)
    counts = success_counts(rows)

    # --- tabelas + wilcoxon em markdown ---
    md = ["# Análise do benchmark\n", "## Taxa de sucesso por método\n"]
    md.append("| Método | ok | total | taxa |")
    md.append("|---|---|---|---|")
    for b in BRANCH_ORDER:
        if b in counts:
            ok, tot = counts[b]
            md.append(f"| {b} | {ok} | {tot} | {100*ok/tot:.1f}% |")
    for mode in MODES:
        md.append(f"\n## Médias por método — modo {mode}\n")
        md.append(mean_table_md(rows, mode))
    md.append("\n## Wilcoxon pareado IA × Blander\n")
    md.append(wilcoxon_md(rows))
    summary = "\n".join(md) + "\n"

    (args.out / "analysis_summary.md").write_text(summary, encoding="utf-8")
    print(summary)

    # --- gráficos ---
    g1 = plot_success(counts, args.out)
    g2 = plot_boxplot(rows, args.out, metric="f_score_001", mode="matte")
    g3 = plot_scatter(rows, args.out, metric="f_score_001")

    print(f"\nGráficos gerados:\n  {g1}\n  {g2}\n  {g3}")
    print(f"Resumo: {args.out / 'analysis_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
