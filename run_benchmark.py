"""Entry point uniforme para benchmark da branch IA (Hunyuan3D-2mv).

Recebe 4 PNGs cardeais (front/left/back/right) e produz um GLB. Usado
pelo orquestrador em `eval/benchmark.py` quando ele itera dataset ×
branches.

Contrato: ver `back/eval/RUN_BENCHMARK_CONTRACT.md`.

Exemplo de invocação manual:

    python run_benchmark.py \\
        --views-dir  C:/TCC_eval_data/synthetic_views/perfume_001/ \\
        --output-glb C:/TCC_eval_data/outputs/ia/perfume_001.glb

Saída em stdout (uma linha JSON):

    {"status":"ok","glb":"...","duration_s":42.1,"peak_vram_mb":null}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

# Imports do projeto (mesma estrutura usada pelo `uvicorn app.main:app`).
from app.main import build_pipeline
from app.modules.captures.processor import ProcessingInput
from app.storage.local_storage import LocalStorage

VIEW_ORDER = ("front", "left", "back", "right")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Roda o IntegratedPipeline (Hunyuan3D-2mv) em 4 vistas cardeais "
            "e salva o GLB. Usado pelo orquestrador de benchmarks."
        )
    )
    p.add_argument(
        "--views-dir",
        type=Path,
        required=True,
        help="Diretório com {front,left,back,right}.png",
    )
    p.add_argument(
        "--output-glb",
        type=Path,
        required=True,
        help="Caminho exato onde o GLB resultante será escrito.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Timeout total em segundos (default 1800 = 30min).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Logs extras em stderr.",
    )
    return p.parse_args()


def emit(payload: dict) -> None:
    """Imprime uma linha JSON no stdout (formato esperado pelo orquestrador)."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def collect_views(views_dir: Path) -> list[Path]:
    """Valida e retorna as 4 vistas cardeais no diretório."""
    paths: list[Path] = []
    missing: list[str] = []
    for view in VIEW_ORDER:
        png = views_dir / f"{view}.png"
        if png.exists():
            paths.append(png)
        else:
            missing.append(view)
    if missing:
        emit(
            {
                "status": "error",
                "error": f"vistas ausentes em {views_dir}: {missing}",
                "duration_s": 0.0,
            }
        )
        sys.exit(2)
    return paths


async def run_pipeline_async(
    output_glb: Path,
    image_paths: list[Path],
    views: list[str],
) -> None:
    """Roda o IntegratedPipeline em modo síncrono (sem queue/HTTP).

    Usa o output_glb como base do storage temporário para preservar
    artefatos intermediários (preprocessed/masked/raw.glb) no caso de
    alguma análise post-mortem.
    """
    storage = LocalStorage(root=output_glb.parent / ".tmp_storage")
    storage.ensure_dirs()
    pipeline = build_pipeline(storage=storage)

    input_data = ProcessingInput(
        job_id=output_glb.stem,
        image_paths=image_paths,
        output_path=output_glb,
        views=views,
    )
    await pipeline.process(input_data)


def main() -> int:
    args = parse_args()
    if args.verbose:
        print(f"[benchmark IA] views_dir={args.views_dir}", file=sys.stderr)
        print(f"[benchmark IA] output_glb={args.output_glb}", file=sys.stderr)

    image_paths = collect_views(args.views_dir)
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        asyncio.run(
            asyncio.wait_for(
                run_pipeline_async(args.output_glb, image_paths, list(VIEW_ORDER)),
                timeout=args.timeout,
            )
        )
    except asyncio.TimeoutError:
        emit(
            {
                "status": "error",
                "error": f"timeout após {args.timeout}s",
                "duration_s": time.monotonic() - start,
            }
        )
        return 124
    except Exception as exc:
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        emit(
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "duration_s": time.monotonic() - start,
            }
        )
        return 1

    duration = time.monotonic() - start
    if not args.output_glb.exists():
        emit(
            {
                "status": "error",
                "error": "pipeline terminou sem escrever o GLB",
                "duration_s": duration,
            }
        )
        return 1

    emit(
        {
            "status": "ok",
            "glb": str(args.output_glb),
            "duration_s": duration,
            "peak_vram_mb": None,  # branch IA ainda não mede VRAM aqui
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
