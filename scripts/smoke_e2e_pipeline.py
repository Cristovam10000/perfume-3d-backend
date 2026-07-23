"""Smoke end-to-end do IntegratedPipeline de producao.

Monta o pipeline real via `build_pipeline()` (mesma factory do FastAPI,
lendo o `.env`) e processa uma pasta de fotos, sem subir servidor nem
tocar banco (use CACHE_ENABLED=false para ficar 100% offline de DB).

Uso:
    cd C:\\TCC\\back
    .\\.venv\\Scripts\\python.exe scripts\\smoke_e2e_pipeline.py "C:\\TCC\\imagens para teste 2" \
        --output tmp/e2e_teste2/final.glb

As fotos sao ordenadas por nome; nomes contendo front/left/back/right
viram hints de vista (o resto vira "extra"). Artefatos intermediarios
ficam em storage/tmp/pipeline/<job_id>/.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent
if str(BACK_ROOT) not in sys.path:
    sys.path.insert(0, str(BACK_ROOT))

from app.config import settings
from app.core.logging import configure_logging
from app.main import build_pipeline
from app.modules.captures.processor import ProcessingInput

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}
VISTAS_CONHECIDAS = ("front", "left", "back", "right")


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def coletar_fotos(pasta: Path) -> list[Path]:
    fotos = sorted(
        p for p in pasta.iterdir()
        if p.suffix.lower() in EXTENSOES_IMAGEM
    )
    if not fotos:
        raise SystemExit(f"Nenhuma imagem em {pasta}")
    return fotos


def inferir_views(fotos: list[Path]) -> list[str | None]:
    """Extrai hints de vista do nome do arquivo (ex: 01_front.jpeg)."""
    views: list[str | None] = []
    for foto in fotos:
        nome = foto.stem.lower()
        hint = next((v for v in VISTAS_CONHECIDAS if v in nome), None)
        views.append(hint)
    return views


async def main() -> int:
    parser = argparse.ArgumentParser(prog="smoke_e2e_pipeline")
    parser.add_argument("pasta", type=Path, help="pasta com as fotos do frasco")
    parser.add_argument(
        "--output", type=Path, default=Path("tmp/e2e/final.glb"),
        help="caminho do GLB final",
    )
    parser.add_argument(
        "--job-id", default=f"e2e-{int(time.time())}",
        help="job id usado no workspace de artefatos intermediarios",
    )
    args = parser.parse_args()

    configure_logging()

    fotos = coletar_fotos(args.pasta)
    views = inferir_views(fotos)
    log(f"pipeline_mode={settings.pipeline_mode}, hunyuan={settings.hunyuan_url}")
    log(f"{len(fotos)} foto(s): {[f.name for f in fotos]}")
    log(f"views: {views}")

    pipeline = build_pipeline()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    inicio = time.perf_counter()
    resultado = await pipeline.process(
        ProcessingInput(
            job_id=args.job_id,
            image_paths=fotos,
            output_path=args.output,
            views=views,
        )
    )
    duracao = time.perf_counter() - inicio

    log(f"origem   = {resultado.origem}")
    log(f"mensagem = {resultado.message}")
    log(f"output   = {resultado.output_path}")
    log(f"duracao  = {duracao:.1f}s")
    log(f"artefatos intermediarios: storage/tmp/pipeline/{args.job_id}/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
