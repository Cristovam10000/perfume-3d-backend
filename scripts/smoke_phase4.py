"""Smoke manual da Fase 4: foto crua -> preprocess -> rembg -> Hunyuan -> Cleanup -> Refiner.

Permite validar visualmente o pipeline completo da Fase 4 (preprocess + cleanup +
refiner) com fotos reais antes da integração via FastAPI da Fase 7. Não toca
em FastAPI, banco ou worker.

Uso:
    # 1. Subir o container do Hunyuan
    docker compose up -d hunyuan

    # 2. Esperar ~2 min, verificar:
    curl http://localhost:7860/health

    # 3. Tirar 4-6 fotos do perfume e copiar pra alguma pasta:
    python scripts/smoke_phase4.py C:\\imagens_Novas --open
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import httpx

SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent
if str(BACK_ROOT) not in sys.path:
    sys.path.insert(0, str(BACK_ROOT))

from app.modules.captures.background_remover import RembgBackgroundRemover
from app.modules.captures.image_preprocessor import StandardImagePreprocessor
from app.modules.captures.mesh_cleaner import BlenderMeshCleaner, MeshCleanupInput
from app.modules.captures.mesh_refiner import BlenderMeshRefiner, RefinementInput
from app.modules.captures.processor import Hunyuan3DProcessor, ProcessingInput


EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}


def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


class CronometroEtapa:
    def __init__(self, rotulo: str):
        self.rotulo = rotulo
        self.inicio = 0.0

    def __enter__(self) -> "CronometroEtapa":
        self.inicio = time.perf_counter()
        log(f"{self.rotulo}...")
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        duracao = round(time.perf_counter() - self.inicio)
        status = "falhou" if exc_type else "ok"
        log(f"{self.rotulo}: {status} em {duracao}s")


def listar_fotos(pasta: Path, max_images: int) -> list[Path]:
    if not pasta.exists() or not pasta.is_dir():
        raise FileNotFoundError(f"Pasta de fotos nao encontrada: {pasta}")

    fotos = [
        item
        for item in sorted(pasta.iterdir())
        if item.is_file() and item.suffix.lower() in EXTENSOES_IMAGEM
    ]
    if not fotos:
        raise ValueError(f"Nenhuma foto encontrada em {pasta}")
    return fotos[:max_images]


def preparar_saida(tmp_root: Path, storage_root: Path) -> tuple[Path, Path, Path, Path]:
    """Cria subdirs de tmp/smoke (preprocessed, masked) e storage/smoke.

    Limpa apenas artefatos conhecidos do smoke anterior; preserva o resto.
    """
    preprocessed_dir = tmp_root / "preprocessed"
    masks_dir = tmp_root / "masked"
    smoke_storage = storage_root / "smoke"
    preprocessed_smoke = smoke_storage / "preprocessed"
    masked_smoke = smoke_storage / "masked"

    for caminho in (preprocessed_dir, masks_dir, smoke_storage, preprocessed_smoke, masked_smoke):
        caminho.mkdir(parents=True, exist_ok=True)

    for sub in (preprocessed_dir, masks_dir, preprocessed_smoke, masked_smoke):
        for arquivo in sub.iterdir():
            if arquivo.is_file():
                arquivo.unlink()

    for nome in ("raw.glb", "cleaned.glb", "refined.glb"):
        caminho = tmp_root / nome
        if caminho.exists():
            caminho.unlink()

    return preprocessed_dir, masks_dir, smoke_storage, preprocessed_smoke


async def preprocessar_fotos(fotos: list[Path], destino: Path) -> list[Path]:
    """Aplica StandardImagePreprocessor em cada foto, salva como JPEG."""
    preprocessor = StandardImagePreprocessor()
    saidas: list[Path] = []
    for indice, foto in enumerate(fotos, start=1):
        saida = destino / f"{indice:02d}_{foto.stem}.jpg"
        log(f"  preprocessando {indice}/{len(fotos)}: {foto.name}")
        try:
            await preprocessor.preprocess(foto, saida)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Dependencias de visao ausentes. Instale com: "
                ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-vision.txt"
            ) from exc
        saidas.append(saida)
    return saidas


async def segmentar_fotos(fotos: list[Path], masks_dir: Path) -> list[Path]:
    remover = RembgBackgroundRemover()
    segmentadas: list[Path] = []

    for indice, foto in enumerate(fotos, start=1):
        saida = masks_dir / f"{indice:02d}_{foto.stem}.png"
        log(f"  segmentando {indice}/{len(fotos)}: {foto.name}")
        try:
            await remover.remove(foto, saida)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Dependencias de visao ausentes. Instale com: "
                ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-vision.txt"
            ) from exc
        segmentadas.append(saida)

    return segmentadas


async def aguardar_hunyuan(service_url: str, timeout_seconds: float) -> None:
    deadline = time.perf_counter() + timeout_seconds
    async with httpx.AsyncClient(base_url=service_url, timeout=10.0) as cliente:
        while time.perf_counter() < deadline:
            try:
                resp = await cliente.get("/health")
                dados = resp.json()
                if dados.get("status") == "ready":
                    return
                log(f"  Hunyuan ainda carregando: {dados}")
            except Exception as exc:
                log(f"  aguardando Hunyuan em {service_url}: {exc}")
            await asyncio.sleep(5)

    raise RuntimeError(
        f"Hunyuan nao ficou pronto em {timeout_seconds:.0f}s. "
        "Suba com `docker compose up -d hunyuan` e confira /health."
    )


async def gerar_hunyuan(
    imagens_segmentadas: list[Path],
    output_glb: Path,
    *,
    service_url: str,
    wait_seconds: float,
) -> None:
    await aguardar_hunyuan(service_url, wait_seconds)
    processor = Hunyuan3DProcessor(service_url=service_url, timeout_seconds=900.0)
    await processor.process(
        ProcessingInput(
            job_id="smoke-phase4",
            image_paths=imagens_segmentadas,
            output_path=output_glb,
        )
    )


async def limpar_mesh(input_glb: Path, output_glb: Path) -> None:
    cleaner = BlenderMeshCleaner(timeout_seconds=180.0)
    resultado = await cleaner.clean(
        MeshCleanupInput(
            input_glb=input_glb,
            output_glb=output_glb,
        )
    )
    log(
        f"  ilhas removidas={resultado.islands_removed}, "
        f"furos preenchidos={resultado.holes_filled}, "
        f"faces finais={resultado.final_face_count}"
    )


async def refinar_mesh(input_glb: Path, output_glb: Path) -> None:
    refiner = BlenderMeshRefiner(timeout_seconds=180.0)
    await refiner.refine(
        RefinementInput(
            input_glb=input_glb,
            output_glb=output_glb,
        )
    )


def copiar_para_storage(
    *,
    raw_glb: Path,
    cleaned_glb: Path,
    refined_glb: Path,
    preprocessed: list[Path],
    segmentadas: list[Path],
    smoke_storage: Path,
) -> None:
    shutil.copy2(raw_glb, smoke_storage / "raw.glb")
    shutil.copy2(cleaned_glb, smoke_storage / "cleaned.glb")
    shutil.copy2(refined_glb, smoke_storage / "refined.glb")
    for arquivo in preprocessed:
        shutil.copy2(arquivo, smoke_storage / "preprocessed" / arquivo.name)
    for arquivo in segmentadas:
        shutil.copy2(arquivo, smoke_storage / "masked" / arquivo.name)


def montar_urls(public_base_url: str) -> tuple[str, str, str, str]:
    base = public_base_url.rstrip("/")
    raw_url = f"{base}/files/smoke/raw.glb"
    cleaned_url = f"{base}/files/smoke/cleaned.glb"
    refined_url = f"{base}/files/smoke/refined.glb"
    viewer_src = quote("/files/smoke/refined.glb", safe="")
    viewer_url = f"{base}/files/model_viewer.html?src={viewer_src}"
    return raw_url, cleaned_url, refined_url, viewer_url


async def main_async(args: argparse.Namespace) -> int:
    fotos_dir = args.photos_dir.resolve()
    tmp_root = args.tmp_root.resolve()
    storage_root = args.storage_root.resolve()

    fotos = listar_fotos(fotos_dir, args.max_images)
    preprocessed_dir, masks_dir, smoke_storage, _ = preparar_saida(tmp_root, storage_root)
    raw_glb = tmp_root / "raw.glb"
    cleaned_glb = tmp_root / "cleaned.glb"
    refined_glb = tmp_root / "refined.glb"

    log(f"fotos = {fotos_dir}")
    log(f"usando {len(fotos)} foto(s): {[foto.name for foto in fotos]}")

    with CronometroEtapa(f"(1/6) preprocessando {len(fotos)} fotos"):
        fotos_preprocessadas = await preprocessar_fotos(fotos, preprocessed_dir)

    with CronometroEtapa(f"(2/6) segmentando {len(fotos)} fotos com rembg"):
        imagens_segmentadas = await segmentar_fotos(fotos_preprocessadas, masks_dir)

    with CronometroEtapa("(3/6) gerando GLB no Hunyuan"):
        await gerar_hunyuan(
            imagens_segmentadas,
            raw_glb,
            service_url=args.hunyuan_url,
            wait_seconds=args.hunyuan_wait_seconds,
        )

    with CronometroEtapa("(4/6) limpando mesh (ilhas, furos, normais)"):
        await limpar_mesh(raw_glb, cleaned_glb)

    with CronometroEtapa("(5/6) refinando shader de vidro"):
        await refinar_mesh(cleaned_glb, refined_glb)

    with CronometroEtapa("(6/6) copiando para storage/smoke"):
        copiar_para_storage(
            raw_glb=raw_glb,
            cleaned_glb=cleaned_glb,
            refined_glb=refined_glb,
            preprocessed=fotos_preprocessadas,
            segmentadas=imagens_segmentadas,
            smoke_storage=smoke_storage,
        )

    raw_url, cleaned_url, refined_url, viewer_url = montar_urls(args.public_base_url)
    log("pronto! abra:")
    print(f"   Cru:      {raw_url}", flush=True)
    print(f"   Limpo:    {cleaned_url}", flush=True)
    print(f"   Refinado: {refined_url}", flush=True)
    print(f"   Viewer:   {viewer_url}", flush=True)

    if args.open:
        webbrowser.open(viewer_url)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="smoke_phase4")
    parser.add_argument("photos_dir", type=Path)
    parser.add_argument("--tmp-root", type=Path, default=BACK_ROOT / "tmp" / "smoke")
    parser.add_argument("--storage-root", type=Path, default=BACK_ROOT / "storage")
    parser.add_argument("--hunyuan-url", default="http://localhost:7860")
    parser.add_argument("--public-base-url", default="http://localhost:8000")
    parser.add_argument("--hunyuan-wait-seconds", type=float, default=180.0)
    parser.add_argument("--max-images", type=int, default=6)
    parser.add_argument("--open", action="store_true", help="abre o viewer refinado no browser")
    return parser.parse_args()


def main() -> int:
    try:
        return asyncio.run(main_async(parse_args()))
    except Exception as exc:
        log(f"ERRO: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
