"""Smoke manual da Fase 5: foto real -> Hunyuan -> cleanup/refiner -> label real.

Valida visualmente a aplicacao da label real extraida da foto antes da
integracao via FastAPI/worker. Nao toca em banco nem em endpoints.

Uso:
    cd C:\\TCC\\back
    .\\.venv\\Scripts\\python.exe scripts\\smoke_phase5.py C:\\imagens_Novas --open
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
from app.modules.captures.label_extractor import HomographyLabelExtractor
from app.modules.captures.label_projector import (
    BlenderLabelProjector,
    LabelProjectionInput,
)
from app.modules.captures.label_upscaler import LanczosLabelUpscaler
from app.modules.captures.mesh_refiner import BlenderMeshRefiner, RefinementInput
from app.modules.captures.processor import Hunyuan3DProcessor, ProcessingInput
from app.modules.captures.view_texture_projector import (
    AXIS_TOP,
    BlenderViewTextureProjector,
    ViewTextureProjectionInput,
)


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


def limpar_arquivos(diretorio: Path) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    for arquivo in diretorio.iterdir():
        if arquivo.is_file():
            arquivo.unlink()


def preparar_saida(
    tmp_root: Path,
    storage_root: Path,
    *,
    preserve_raw: bool = False,
) -> tuple[Path, Path, Path]:
    preprocessed_dir = tmp_root / "preprocessed"
    masks_dir = tmp_root / "masked"
    smoke_storage = storage_root / "smoke"
    preprocessed_smoke = smoke_storage / "preprocessed"
    masked_smoke = smoke_storage / "masked"

    for sub in (preprocessed_dir, masks_dir, preprocessed_smoke, masked_smoke):
        limpar_arquivos(sub)

    smoke_storage.mkdir(parents=True, exist_ok=True)
    for nome in (
        "raw.glb",
        "cleaned.glb",
        "refined.glb",
        "with_label.glb",
        "label_raw.png",
        "label_upscaled.png",
    ):
        if preserve_raw and nome == "raw.glb":
            continue
        for base in (tmp_root, smoke_storage):
            caminho = base / nome
            if caminho.exists():
                caminho.unlink()

    return preprocessed_dir, masks_dir, smoke_storage


async def preprocessar_fotos(fotos: list[Path], destino: Path) -> list[Path]:
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


async def extrair_label(
    fotos: list[Path],
    mascaras: list[Path],
    output_path: Path,
    *,
    min_confidence: float,
) -> Path | None:
    extrator = HomographyLabelExtractor()
    melhor_conf = 0.0
    melhor_path: Path | None = None

    for indice, (foto, mascara) in enumerate(zip(fotos, mascaras), start=1):
        candidato = output_path.parent / f"label_candidate_{indice:02d}.png"
        log(f"  tentando label {indice}/{len(fotos)}: {foto.name}")
        try:
            resultado = await extrator.extract(foto, mascara, candidato)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Dependencias de visao ausentes. Instale com: "
                ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-vision.txt"
            ) from exc

        if resultado is None:
            continue
        log(
            f"    candidato: confidence={resultado.confidence:.3f}, "
            f"aspect={resultado.aspect_ratio:.3f}"
        )
        if resultado.confidence > melhor_conf:
            melhor_conf = resultado.confidence
            melhor_path = resultado.image_path
        if resultado.confidence > min_confidence:
            shutil.copy2(resultado.image_path, output_path)
            return output_path

    if melhor_path is not None:
        log(
            "  AVISO: nenhuma label passou o limiar "
            f"{min_confidence:.2f}; melhor confidence={melhor_conf:.3f}"
        )
    else:
        log("  AVISO: nenhuma label plausivel encontrada")
    return None


async def extrair_label_por_recorte(
    fotos: list[Path],
    mascaras: list[Path],
    output_path: Path,
) -> Path | None:
    """Fallback pragmatico: recorta a regiao com mais bordas dentro do frasco.

    Alguns perfumes nao tem uma label retangular; o texto e impresso direto no
    vidro. A homografia nao acha quadrilatero nesses casos, entao este fallback
    escolhe uma faixa frontal/direita rica em bordas para projetar como decal.
    """
    return await asyncio.to_thread(
        _extrair_label_por_recorte_sync,
        fotos,
        mascaras,
        output_path,
    )


def _extrair_label_por_recorte_sync(
    fotos: list[Path],
    mascaras: list[Path],
    output_path: Path,
) -> Path | None:
    from PIL import Image, ImageFilter, ImageStat

    melhor: tuple[float, Image.Image, str] | None = None
    for indice, (foto, mascara) in enumerate(zip(fotos, mascaras), start=1):
        with Image.open(foto) as img, Image.open(mascara) as mask_img:
            imagem = img.convert("RGB")
            if "A" in mask_img.getbands():
                alpha = mask_img.getchannel("A")
            else:
                alpha = mask_img.convert("L")

            bbox = alpha.getbbox()
            if bbox is None:
                continue

            x0, y0, x1, y1 = bbox
            largura = max(1, x1 - x0)
            altura = max(1, y1 - y0)
            regioes = [
                ("direita", 0.42, 0.16, 0.95, 0.90),
                ("centro", 0.22, 0.18, 0.82, 0.90),
                ("frente", 0.12, 0.20, 0.88, 0.88),
            ]

            for nome, rx0, ry0, rx1, ry1 in regioes:
                crop_box = (
                    int(x0 + largura * rx0),
                    int(y0 + altura * ry0),
                    int(x0 + largura * rx1),
                    int(y0 + altura * ry1),
                )
                crop = imagem.crop(crop_box)
                if crop.width < 40 or crop.height < 40:
                    continue

                cinza = crop.convert("L")
                bordas = cinza.filter(ImageFilter.FIND_EDGES)
                stat_bordas = ImageStat.Stat(bordas)
                stat_cinza = ImageStat.Stat(cinza)
                score = stat_bordas.mean[0] + stat_cinza.stddev[0] * 0.35

                if melhor is None or score > melhor[0]:
                    melhor = (score, crop.copy(), f"{indice}:{nome}")

    if melhor is None:
        return None

    score, crop, origem = melhor
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path, format="PNG")
    log(f"  fallback por recorte: origem={origem}, score={score:.2f}")
    return output_path


async def upscale_label(input_path: Path, output_path: Path, target_size: int) -> Path:
    upscaler = LanczosLabelUpscaler(target_size=target_size)
    return await upscaler.upscale(input_path, output_path)


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
    timeout_seconds: float,
    octree_resolution: int,
    num_inference_steps: int,
    guidance_scale: float,
    mc_algo: str,
    texture_resolution: int,
) -> None:
    await aguardar_hunyuan(service_url, wait_seconds)
    processor = Hunyuan3DProcessor(
        service_url=service_url,
        timeout_seconds=timeout_seconds,
        octree_resolution=octree_resolution,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        mc_algo=mc_algo,
        texture_resolution=texture_resolution,
    )
    try:
        await processor.process(
            ProcessingInput(
                job_id="smoke-phase5",
                image_paths=imagens_segmentadas,
                output_path=output_glb,
            )
        )
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Hunyuan excedeu o timeout de "
            f"{timeout_seconds:.0f}s durante /generate. "
            "Isso costuma acontecer quando a textura esta habilitada, "
            "a GPU/RAM estao no limite, ou o container travou na inferencia. "
            "Veja `docker logs --tail 120 tcc-hunyuan-1`."
        ) from exc


async def limpar_mesh(input_glb: Path, output_glb: Path, min_island_ratio: float) -> None:
    """Passthrough: a limpeza de malha migrou para o servidor Hunyuan.

    O `BlenderMeshCleaner` foi removido do backend (FloaterRemover +
    DegenerateFaceRemover rodam no container, HUNYUAN_SHAPE_POSTPROCESS=1).
    `min_island_ratio` fica no argparse so para nao quebrar invocacoes antigas.
    """
    import shutil

    output_glb.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_glb, output_glb)
    log(
        "  limpeza delegada ao servidor Hunyuan — GLB copiado sem alteracao "
        f"(--min-island-ratio={min_island_ratio} ignorado)"
    )


async def refinar_mesh(input_glb: Path, output_glb: Path) -> None:
    refiner = BlenderMeshRefiner(timeout_seconds=180.0)
    await refiner.refine(
        RefinementInput(
            input_glb=input_glb,
            output_glb=output_glb,
        )
    )


async def projetar_label(
    input_glb: Path,
    label_image: Path,
    output_glb: Path,
    *,
    front_axis: str,
) -> None:
    projector = BlenderLabelProjector(timeout_seconds=180.0)
    resultado = await projector.project(
        LabelProjectionInput(
            input_glb=input_glb,
            label_image=label_image,
            output_glb=output_glb,
            front_axis=front_axis,
        )
    )
    log(
        f"  label projetada: face={resultado.target_face_index}, "
        f"coverage={resultado.coverage_ratio:.3f}"
    )


async def segmentar_top(top_image: Path, destino: Path) -> Path:
    """Remove fundo da foto do topo via rembg. Retorna PNG RGBA sem fundo."""
    import asyncio
    from PIL import Image
    import rembg

    def _run() -> Path:
        dados = top_image.read_bytes()
        resultado = rembg.remove(dados)
        saida = destino / f"top_segmented.png"
        saida.parent.mkdir(parents=True, exist_ok=True)
        saida.write_bytes(resultado)
        # Valida que gerou RGBA
        img = Image.open(saida)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
            img.save(saida)
        return saida

    saida = await asyncio.to_thread(_run)
    log(f"  fundo do topo removido: {saida.name}")
    return saida


async def projetar_topo(
    input_glb: Path,
    top_image: Path,
    output_glb: Path,
    tmp_root: Path,
) -> None:
    projector = BlenderViewTextureProjector(timeout_seconds=120.0)
    await projector.project(
        ViewTextureProjectionInput(
            input_glb=input_glb,
            photo=top_image,
            output_glb=output_glb,
            axis=AXIS_TOP,
        )
    )
    log(f"  textura do topo projetada: {output_glb.name}")


def copiar_para_storage(
    *,
    raw_glb: Path,
    cleaned_glb: Path,
    refined_glb: Path,
    with_label_glb: Path,
    preprocessed: list[Path],
    segmentadas: list[Path],
    label_raw: Path | None,
    label_upscaled: Path | None,
    smoke_storage: Path,
) -> None:
    shutil.copy2(raw_glb, smoke_storage / "raw.glb")
    shutil.copy2(cleaned_glb, smoke_storage / "cleaned.glb")
    shutil.copy2(refined_glb, smoke_storage / "refined.glb")
    shutil.copy2(with_label_glb, smoke_storage / "with_label.glb")
    if label_raw is not None and label_raw.exists():
        shutil.copy2(label_raw, smoke_storage / "label_raw.png")
    if label_upscaled is not None and label_upscaled.exists():
        shutil.copy2(label_upscaled, smoke_storage / "label_upscaled.png")
    for arquivo in preprocessed:
        shutil.copy2(arquivo, smoke_storage / "preprocessed" / arquivo.name)
    for arquivo in segmentadas:
        shutil.copy2(arquivo, smoke_storage / "masked" / arquivo.name)


def montar_urls(public_base_url: str) -> tuple[str, str, str, str, str]:
    base = public_base_url.rstrip("/")
    raw_viewer = f"{base}/model_viewer.html?src={quote('/smoke/raw.glb', safe='')}"
    cleaned_viewer = f"{base}/model_viewer.html?src={quote('/smoke/cleaned.glb', safe='')}"
    refined_viewer = f"{base}/model_viewer.html?src={quote('/smoke/refined.glb', safe='')}"
    label_viewer = f"{base}/model_viewer.html?src={quote('/smoke/with_label.glb', safe='')}"
    fastapi_viewer = (
        f"{base}/files/model_viewer.html?"
        f"src={quote('/files/smoke/with_label.glb', safe='')}"
    )
    return raw_viewer, cleaned_viewer, refined_viewer, label_viewer, fastapi_viewer


async def main_async(args: argparse.Namespace) -> int:
    fotos_dir = args.photos_dir.resolve()
    tmp_root = args.tmp_root.resolve()
    storage_root = args.storage_root.resolve()

    fotos = listar_fotos(fotos_dir, args.max_images)
    preprocessed_dir, masks_dir, smoke_storage = preparar_saida(
        tmp_root,
        storage_root,
        preserve_raw=args.reuse_raw,
    )

    raw_glb = tmp_root / "raw.glb"
    cleaned_glb = tmp_root / "cleaned.glb"
    refined_glb = tmp_root / "refined.glb"
    with_label_glb = tmp_root / "with_label.glb"
    with_top_glb  = tmp_root / "with_top.glb"
    label_raw = tmp_root / "label_raw.png"
    label_upscaled = tmp_root / "label_upscaled.png"

    top_image: Path | None = None
    if args.top_image is not None:
        top_image = Path(args.top_image).resolve()
        if not top_image.exists():
            log(f"AVISO: --top-image '{top_image}' nao encontrada, etapa de topo sera pulada")
            top_image = None

    log(f"fotos = {fotos_dir}")
    log(f"usando {len(fotos)} foto(s): {[foto.name for foto in fotos]}")
    if top_image:
        log(f"foto do topo = {top_image.name}")

    with CronometroEtapa(f"(1/8) preprocessando {len(fotos)} fotos"):
        fotos_preprocessadas = await preprocessar_fotos(fotos, preprocessed_dir)

    with CronometroEtapa(f"(2/8) segmentando {len(fotos)} fotos com rembg"):
        imagens_segmentadas = await segmentar_fotos(fotos_preprocessadas, masks_dir)

    with CronometroEtapa("(3/8) extraindo label da foto frontal"):
        if args.no_label:
            label_extraida = None
            log("  --no-label: extracao desativada")
        elif args.label_image is not None:
            if not args.label_image.exists():
                raise FileNotFoundError(f"Label manual nao encontrada: {args.label_image}")
            shutil.copy2(args.label_image, label_raw)
            label_extraida = label_raw
            log(f"  usando label manual: {args.label_image}")
        else:
            label_extraida = await extrair_label(
                fotos_preprocessadas,
                imagens_segmentadas,
                label_raw,
                min_confidence=args.label_min_confidence,
            )
            if label_extraida is None:
                log("  tentando fallback por recorte central/direito")
                label_extraida = await extrair_label_por_recorte(
                    fotos_preprocessadas,
                    imagens_segmentadas,
                    label_raw,
                )

    label_upscaled_path: Path | None = None
    if label_extraida is not None:
        with CronometroEtapa("(4/8) upscalando label (Lanczos)"):
            label_upscaled_path = await upscale_label(
                label_extraida,
                label_upscaled,
                args.label_target_size,
            )
    else:
        log("(4/8) upscalando label (Lanczos): pulado sem label")

    with CronometroEtapa("(5/8) gerando GLB no Hunyuan"):
        if args.reuse_raw:
            if not raw_glb.exists():
                raise FileNotFoundError(
                    f"--reuse-raw foi usado, mas {raw_glb} nao existe"
                )
            log(f"  reutilizando GLB cru existente: {raw_glb}")
        else:
            await gerar_hunyuan(
                imagens_segmentadas,
                raw_glb,
                service_url=args.hunyuan_url,
                wait_seconds=args.hunyuan_wait_seconds,
                timeout_seconds=args.hunyuan_timeout_seconds,
                octree_resolution=args.octree_resolution,
                num_inference_steps=args.num_inference_steps,
                guidance_scale=args.guidance_scale,
                mc_algo=args.mc_algo,
                texture_resolution=args.texture_resolution,
            )

    with CronometroEtapa("(6/8) limpando mesh (conservador)"):
        await limpar_mesh(raw_glb, cleaned_glb, args.min_island_ratio)

    with CronometroEtapa("(7/8) refinando shader de vidro"):
        await refinar_mesh(cleaned_glb, refined_glb)

    with CronometroEtapa("(8/8) projetando label na face frontal"):
        if label_upscaled_path is None:
            log("  AVISO: modo degradado sem label; copiando refined -> with_label")
            shutil.copy2(refined_glb, with_label_glb)
        else:
            await projetar_label(
                refined_glb,
                label_upscaled_path,
                with_label_glb,
                front_axis=args.front_axis,
            )

    # Etapa opcional: projeta foto do topo na tampa
    glb_final = with_label_glb
    if top_image is not None:
        with CronometroEtapa("(+) removendo fundo da foto do topo"):
            top_image_seg = await segmentar_top(top_image, tmp_root)
        with CronometroEtapa("(+) projetando textura do topo na tampa"):
            await projetar_topo(with_label_glb, top_image_seg, with_top_glb, tmp_root)
            glb_final = with_top_glb
    else:
        log("(+) projetando textura do topo: pulado (sem --top-image)")

    copiar_para_storage(
        raw_glb=raw_glb,
        cleaned_glb=cleaned_glb,
        refined_glb=refined_glb,
        with_label_glb=glb_final,
        preprocessed=fotos_preprocessadas,
        segmentadas=imagens_segmentadas,
        label_raw=label_extraida,
        label_upscaled=label_upscaled_path,
        smoke_storage=smoke_storage,
    )

    raw_url, cleaned_url, refined_url, label_url, fastapi_url = montar_urls(
        args.public_base_url
    )
    log("pronto! abra:")
    print(f"   Cru:            {raw_url}", flush=True)
    print(f"   Limpo:          {cleaned_url}", flush=True)
    print(f"   Refinado:       {refined_url}", flush=True)
    print(f"   Com label:      {label_url}", flush=True)
    print(f"   FastAPI (/files): {fastapi_url}", flush=True)

    if args.open:
        webbrowser.open(label_url)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="smoke_phase5")
    parser.add_argument("photos_dir", type=Path)
    parser.add_argument("--tmp-root", type=Path, default=BACK_ROOT / "tmp" / "smoke")
    parser.add_argument("--storage-root", type=Path, default=BACK_ROOT / "storage")
    parser.add_argument("--hunyuan-url", default="http://localhost:7860")
    parser.add_argument("--public-base-url", default="http://localhost:8000")
    parser.add_argument("--hunyuan-wait-seconds", type=float, default=180.0)
    parser.add_argument("--hunyuan-timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--octree-resolution", type=int, default=384)
    parser.add_argument("--num-inference-steps", type=int, default=75)
    parser.add_argument("--guidance-scale", type=float, default=7.5)
    parser.add_argument("--mc-algo", choices=("mc", "dmc"), default="mc")
    parser.add_argument("--texture-resolution", type=int, default=2048)
    parser.add_argument("--max-images", type=int, default=6)
    parser.add_argument("--label-min-confidence", type=float, default=0.3)
    parser.add_argument("--label-target-size", type=int, default=2048)
    parser.add_argument(
        "--label-image",
        type=Path,
        default=None,
        help="PNG/JPG de label ja recortada; pula a extracao automatica",
    )
    parser.add_argument(
        "--no-label",
        action="store_true",
        help="pula extracao e projecao de label; entrega refined.glb como resultado final",
    )
    parser.add_argument("--front-axis", default="front_y_neg")
    parser.add_argument(
        "--top-image",
        type=str,
        default=None,
        help="caminho para foto do topo do frasco; quando fornecida projeta a textura na tampa",
    )
    parser.add_argument(
        "--min-island-ratio",
        type=float,
        default=0.0,
        help="0 copia o GLB sem cleanup; aumente apenas para artefatos soltos claros",
    )
    parser.add_argument(
        "--reuse-raw",
        action="store_true",
        help="reutiliza tmp/smoke/raw.glb e pula a chamada demorada ao Hunyuan",
    )
    parser.add_argument("--open", action="store_true", help="abre o viewer final no browser")
    return parser.parse_args()


def main() -> int:
    try:
        return asyncio.run(main_async(parse_args()))
    except Exception as exc:
        detalhe = str(exc) or repr(exc)
        log(f"ERRO ({type(exc).__name__}): {detalhe}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
