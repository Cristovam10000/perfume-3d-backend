"""Servidor de inferencia Hunyuan3D-2mv.

Roda dentro do container Docker com acesso a GPU. Expoe:

- GET  /health   -> verifica se o modelo esta carregado e pronto
- POST /generate -> recebe 1-6 imagens PNG (RGBA preferencial), devolve GLB binario

Nao importa nada do backend. Toda comunicacao e via HTTP/multipart.
Os modelos sao carregados em background no startup para que /health reflita o
estado real de prontidao antes de /generate ser chamado.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_log = logging.getLogger("hunyuan.server")

# Estado global: carregado uma vez e reutilizado entre requisicoes.
_pipeline_forma = None      # Hunyuan3DDiTFlowMatchingPipeline
_pipeline_textura = None    # Hunyuan3DPaintPipeline
_modelo_carregado = False
_erro_carga: str | None = None

DEFAULT_SHAPE_REPO = "tencent/Hunyuan3D-2"
DEFAULT_SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-mv"
DEFAULT_SHAPE_VARIANT = "bf16"
DEFAULT_OCTREE_RESOLUTION = 384
DEFAULT_NUM_INFERENCE_STEPS = 75
DEFAULT_GUIDANCE_SCALE = 7.5
DEFAULT_MC_ALGO = "mc"
DEFAULT_TEXTURE_RESOLUTION = 2048


class PipelineSemMalhaError(RuntimeError):
    """Sinaliza quando o pipeline retorna sem malha valida."""


def _ler_int_env(nome: str, padrao: int) -> int:
    valor = os.getenv(nome)
    if valor is None or valor.strip() == "":
        return padrao
    try:
        return int(valor)
    except ValueError:
        _log.warning("%s invalido (%r); usando %d.", nome, valor, padrao)
        return padrao


def _ler_bool_env(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip().lower() not in {"0", "false", "no", "off"}


def _ler_str_env(nome: str, padrao: str) -> str:
    valor = os.getenv(nome)
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip()


def _replace_property_getter(instance, property_name: str, new_getter) -> None:
    """Replica o helper do gradio_app para compatibilidade com mmgp."""
    original_class = type(instance)
    original_property = getattr(original_class, property_name, None)
    if original_property is None:
        return

    custom_class = type(f"Custom{original_class.__name__}", (original_class,), {})
    new_property = property(new_getter, original_property.fset)
    setattr(custom_class, property_name, new_property)
    instance.__class__ = custom_class


def _aplicar_offload(nome: str, pipeline, offload, *, pinned_memory: str | None = None) -> None:
    """Aplica profile mmgp no formato esperado pela versao atual da lib."""
    try:
        _replace_property_getter(pipeline, "_execution_device", lambda self: "cuda")
        modulos = offload.extract_models(nome, pipeline)
        orcamento_vram_mb = _ler_int_env("HUNYUAN_VRAM_BUDGET_MB", 2200)
        profile_no = _ler_int_env("MMGP_PROFILE", 4)
        kwargs = {"budgets": {"*": orcamento_vram_mb}}
        if pinned_memory is not None:
            kwargs["pinnedMemory"] = pinned_memory
        offload.profile(
            modulos,
            profile_no=profile_no,
            verboseLevel=1,
            **kwargs,
        )
        _log.info(
            "mmgp profile aplicado em %s (profile=%d, budget=%d MB).",
            nome,
            profile_no,
            orcamento_vram_mb,
        )
    except Exception as exc:
        _log.warning("mmgp profile nao aplicado em %s: %s", nome, exc)


def _filtrar_kwargs(chamavel, kwargs: dict, contexto: str) -> dict:
    """Remove kwargs que a versao instalada do pipeline nao declara."""
    try:
        assinatura = inspect.signature(chamavel)
    except (TypeError, ValueError):
        return kwargs

    parametros = assinatura.parameters
    aceita_kwargs = any(
        parametro.kind == inspect.Parameter.VAR_KEYWORD
        for parametro in parametros.values()
    )
    if aceita_kwargs:
        return kwargs

    filtrados = {chave: valor for chave, valor in kwargs.items() if chave in parametros}
    omitidos = sorted(set(kwargs) - set(filtrados))
    if omitidos:
        _log.warning("%s nao aceita %s; omitindo.", contexto, ", ".join(omitidos))
    return filtrados


def _chamar_pipeline(pipeline, contexto: str, *args, **kwargs):
    return pipeline(*args, **_filtrar_kwargs(pipeline.__call__, kwargs, contexto))


def _normalizar_resultado_pipeline(resultado, contexto: str):
    if isinstance(resultado, (list, tuple)):
        if not resultado:
            raise PipelineSemMalhaError(f"{contexto} retornou lista vazia")
        resultado = resultado[0]
    if resultado is None:
        raise PipelineSemMalhaError(f"{contexto} retornou malha vazia")
    if not hasattr(resultado, "faces"):
        raise PipelineSemMalhaError(
            f"{contexto} retornou objeto sem faces: {type(resultado).__name__}"
        )
    return resultado


def _limpar_cache_cuda() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _parece_oom(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(
        trecho in texto
        for trecho in (
            "out of memory",
            "cuda out",
            "cuda error",
            "oom",
            "cublas",
            "cudnn",
        )
    )


def _carregar_modelos() -> None:
    """Carrega os dois pipelines Hunyuan3D em thread bloqueante."""
    global _pipeline_forma, _pipeline_textura, _modelo_carregado, _erro_carga

    try:
        import torch
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        from hy3dgen.texgen import Hunyuan3DPaintPipeline
        from mmgp import offload

        textura_habilitada = os.getenv("HUNYUAN_ENABLE_TEXTURE", "1").strip().lower()
        if textura_habilitada not in {"0", "false", "no", "off"}:
            # Mesmo reset usado pelo gradio_app oficial. Sem ele, o scheduler do
            # diffusers pode nascer em CUDA e quebrar ao converter tensores para numpy.
            torch.set_default_device("cpu")
            _log.info("Carregando pipeline de textura (Hunyuan3DPaint)...")
            _pipeline_textura = Hunyuan3DPaintPipeline.from_pretrained(DEFAULT_SHAPE_REPO)
            try:
                _pipeline_textura.models["multiview_model"].pipeline.vae.use_slicing = True
            except Exception:
                pass
            _aplicar_offload("texture", _pipeline_textura, offload)
            _log.info("Pipeline de textura carregado.")
        else:
            _pipeline_textura = None
            _log.warning("Pipeline de textura desabilitado por HUNYUAN_ENABLE_TEXTURE=0.")

        shape_repo = _ler_str_env("HUNYUAN_SHAPE_REPO", DEFAULT_SHAPE_REPO)
        shape_subfolder = _ler_str_env(
            "HUNYUAN_SHAPE_SUBFOLDER", DEFAULT_SHAPE_SUBFOLDER
        )
        shape_variant = _ler_str_env("HUNYUAN_SHAPE_VARIANT", DEFAULT_SHAPE_VARIANT)
        _log.info(
            "Carregando pipeline de forma (%s, subfolder=%s, variant=%s)...",
            shape_repo,
            shape_subfolder,
            shape_variant,
        )
        fallback_habilitado = _ler_bool_env(
            "HUNYUAN_ALLOW_SINGLE_VIEW_FALLBACK", True
        )
        candidatos = [(shape_subfolder, shape_variant)]
        if shape_variant != "fp16":
            candidatos.append((shape_subfolder, "fp16"))
        if fallback_habilitado and shape_subfolder != "hunyuan3d-dit-v2-0":
            candidatos.append(("hunyuan3d-dit-v2-0", "fp16"))

        ultimo_erro: Exception | None = None
        for subfolder, variant in candidatos:
            try:
                _pipeline_forma = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                    shape_repo,
                    subfolder=subfolder,
                    variant=variant,
                )
                if subfolder != shape_subfolder or variant != shape_variant:
                    _log.warning(
                        "Shape carregado em fallback: subfolder=%s, variant=%s",
                        subfolder,
                        variant,
                    )
                break
            except Exception as exc:
                ultimo_erro = exc
                _log.exception(
                    "Falha ao carregar shape subfolder=%s variant=%s.",
                    subfolder,
                    variant,
                )
        if _pipeline_forma is None:
            raise ultimo_erro or RuntimeError("Pipeline de forma nao foi carregado")

        # Profile 4 e o default seguro para RTX 5050 com 8GB. Perfis menores
        # podem acelerar, mas tendem a exigir mais VRAM.
        _aplicar_offload("shape", _pipeline_forma, offload, pinned_memory="shape/model")
        _log.info("Pipeline de forma carregado. Servidor pronto.")

        _modelo_carregado = True

    except Exception as exc:
        _log.exception("Falha ao carregar modelos: %s", exc)
        _erro_carga = str(exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia carga dos modelos em thread separada para nao bloquear o startup
    # e permitir que /health responda imediatamente com "loading".
    asyncio.create_task(asyncio.to_thread(_carregar_modelos))
    yield


app = FastAPI(
    title="Hunyuan3D-2mv Inference Server",
    description="Servico de geracao de modelos 3D a partir de fotos de produtos.",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Retorna 'ready' quando o modelo estiver carregado, 'loading' enquanto aguarda."""
    if _erro_carga is not None:
        return {"status": "error", "detail": _erro_carga}
    if _modelo_carregado:
        return {"status": "ready"}
    return {"status": "loading"}


@app.post("/generate")
async def generate(
    images: List[UploadFile] = File(
        ...,
        description="1 a 6 imagens PNG do produto (RGBA preferencial)",
    ),
    octree_resolution: int = Form(
        DEFAULT_OCTREE_RESOLUTION,
        description="Resolucao da octree; mais alto = mais detalhe e mais VRAM",
    ),
    num_inference_steps: int = Form(
        DEFAULT_NUM_INFERENCE_STEPS,
        description="Passos de inferencia; mais = mais detalhe, mais lento",
    ),
    guidance_scale: float = Form(
        DEFAULT_GUIDANCE_SCALE,
        description="CFG/guidance da forma",
    ),
    mc_algo: str = Form(
        DEFAULT_MC_ALGO,
        description="Algoritmo de marching cubes: dmc ou mc",
    ),
    texture_resolution: int = Form(
        DEFAULT_TEXTURE_RESOLUTION,
        description="Resolucao alvo da textura quando suportado",
    ),
):
    """Gera um modelo 3D GLB a partir de fotos do produto."""
    if not _modelo_carregado:
        raise HTTPException(
            status_code=503,
            detail="Modelos ainda sendo carregados. Tente novamente em alguns instantes.",
        )

    if not images:
        raise HTTPException(status_code=422, detail="Pelo menos 1 imagem e obrigatoria.")

    mc_algo_normalizado = mc_algo.strip().lower()
    if mc_algo_normalizado not in {"mc", "dmc"}:
        raise HTTPException(status_code=422, detail="mc_algo deve ser 'mc' ou 'dmc'.")

    # Hunyuan3D-2mv aceita no maximo 6 vistas; imagens extras sao descartadas.
    imagens_usadas = images[:6]

    return await asyncio.to_thread(
        _inferir_sincrono,
        imagens_usadas,
        octree_resolution,
        num_inference_steps,
        guidance_scale,
        mc_algo_normalizado,
        texture_resolution,
    )


def _inferir_sincrono(
    imagens: List[UploadFile],
    octree_resolution: int,
    num_inference_steps: int,
    guidance_scale: float,
    mc_algo: str,
    texture_resolution: int,
) -> Response:
    """Executa geracao de forma + texturizacao em thread."""
    from PIL import Image

    imagens_pil = []
    for upload in imagens:
        dados = upload.file.read()
        img = Image.open(io.BytesIO(dados)).convert("RGBA")
        imagens_pil.append(img)

    _log.info(
        "Iniciando forma com %d imagem(ns), octree=%d, steps=%d, guidance=%.2f, mc=%s",
        len(imagens_pil),
        octree_resolution,
        num_inference_steps,
        guidance_scale,
        mc_algo,
    )

    malha = _gerar_forma_com_fallback(
        imagens_pil,
        octree_resolution=octree_resolution,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        mc_algo=mc_algo,
    )
    _log.info("Forma gerada com sucesso.")

    if _pipeline_textura is None:
        _log.warning("Textura desabilitada; exportando GLB apenas com forma.")
        malha_texturizada = malha
    else:
        malha_texturizada = _texturizar_com_fallback(
            malha,
            imagens_pil,
            texture_resolution=texture_resolution,
        )
        _log.info("Texturizacao concluida.")

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as arq_tmp:
        caminho_tmp = Path(arq_tmp.name)

    try:
        malha_texturizada.export(str(caminho_tmp))
        bytes_glb = caminho_tmp.read_bytes()
    finally:
        caminho_tmp.unlink(missing_ok=True)

    _log.info("GLB exportado: %d bytes.", len(bytes_glb))
    return Response(content=bytes_glb, media_type="model/gltf-binary")


_MV_VIEW_KEYS = ("front", "left", "back", "right")


def _montar_entrada_forma(imagens_pil: list):
    """Adapta a lista de PIL.Images ao formato aceito pelo checkpoint ativo.

    `Hunyuan3DDiTFlowMatchingPipeline.__call__` aceita:
      - PIL.Image (single-view, checkpoint v2-0)
      - dict[str, PIL.Image] (multi-view, checkpoint v2-mv) com keys
        'front', 'left', 'back', 'right' nessa ordem cardinal

    Passar list[PIL.Image] direto faz o `prepare_image` interpretar como
    list[str] e o pipeline retornar uma malha invalida sem levantar excecao.
    """
    if not imagens_pil:
        raise ValueError("imagens_pil vazio")

    processor = getattr(_pipeline_forma, "image_processor", None)
    eh_multiview = type(processor).__name__ == "MVImageProcessorV2"

    if not eh_multiview:
        return imagens_pil[0]

    fotos = imagens_pil[: len(_MV_VIEW_KEYS)]
    image_dict = {chave: foto for chave, foto in zip(_MV_VIEW_KEYS, fotos)}
    _log.info(
        "Montando entrada multi-view com %d vista(s): %s",
        len(image_dict),
        list(image_dict.keys()),
    )
    return image_dict


def _gerar_forma_com_fallback(
    imagens_pil: list,
    *,
    octree_resolution: int,
    num_inference_steps: int,
    guidance_scale: float,
    mc_algo: str,
):
    candidatos: list[tuple[int, str]] = []

    def adicionar(octree: int, algoritmo: str) -> None:
        item = (max(64, int(octree)), algoritmo)
        if item not in candidatos:
            candidatos.append(item)

    adicionar(octree_resolution, mc_algo)
    if mc_algo != "mc":
        adicionar(octree_resolution, "mc")
    if octree_resolution > 256:
        adicionar(256, "mc")

    image_input = _montar_entrada_forma(imagens_pil)

    ultimo_erro: Exception | None = None
    for octree, algoritmo in candidatos:
        kwargs = {
            "num_inference_steps": num_inference_steps,
            "octree_resolution": octree,
            "guidance_scale": guidance_scale,
            "mc_algo": algoritmo,
        }
        try:
            _log.info("Tentando forma: octree=%d, mc=%s", octree, algoritmo)
            resultado = _chamar_pipeline(_pipeline_forma, "shape", image_input, **kwargs)
            return _normalizar_resultado_pipeline(
                resultado,
                f"shape octree={octree}, mc={algoritmo}",
            )
        except TypeError as exc:
            ultimo_erro = exc
            _log.warning(
                "Pipeline recusou parametros avancados (%s); tentando baseline.",
                exc,
            )
            baseline = {
                "num_inference_steps": num_inference_steps,
                "octree_resolution": octree,
            }
            try:
                resultado = _chamar_pipeline(
                    _pipeline_forma,
                    "shape-baseline",
                    image_input,
                    **baseline,
                )
                return _normalizar_resultado_pipeline(
                    resultado,
                    f"shape-baseline octree={octree}",
                )
            except PipelineSemMalhaError as fallback_exc:
                ultimo_erro = fallback_exc
                _log.warning(
                    "Fallback de forma nao gerou malha; tentando proxima opcao: %s",
                    fallback_exc,
                )
                _limpar_cache_cuda()
            except Exception as fallback_exc:
                ultimo_erro = fallback_exc
                if not _parece_oom(fallback_exc):
                    raise
                _log.warning("Fallback de forma estourou VRAM: %s", fallback_exc)
                _limpar_cache_cuda()
        except PipelineSemMalhaError as exc:
            ultimo_erro = exc
            _log.warning("Forma nao gerou malha; tentando fallback: %s", exc)
            _limpar_cache_cuda()
        except Exception as exc:
            ultimo_erro = exc
            if not _parece_oom(exc):
                raise
            _log.warning("Forma estourou VRAM; tentando fallback menor: %s", exc)
            _limpar_cache_cuda()

    if ultimo_erro is not None:
        raise ultimo_erro
    raise RuntimeError("Nenhuma tentativa de forma foi executada")


def _texturizar_com_fallback(malha, imagens_pil: list, *, texture_resolution: int):
    kwargs = {"texture_resolution": max(512, int(texture_resolution))}
    usar_multiview = _ler_bool_env("HUNYUAN_TEXTURE_MULTI_VIEW", True)

    if usar_multiview and len(imagens_pil) > 1:
        try:
            referencias = imagens_pil[:6]
            _log.info(
                "Tentando texturizacao multi-view com %d imagem(ns), texture=%d...",
                len(referencias),
                kwargs["texture_resolution"],
            )
            resultado = _chamar_pipeline(
                _pipeline_textura,
                "texture-multiview",
                malha,
                referencias,
                **kwargs,
            )
            return _normalizar_resultado_pipeline(resultado, "texture-multiview")
        except Exception as exc:
            _log.warning(
                "Textura multi-view indisponivel/falhou; usando primeira vista: %s",
                exc,
            )
            _limpar_cache_cuda()

    _log.info("Iniciando texturizacao com 1 imagem de referencia...")
    try:
        resultado = _chamar_pipeline(
            _pipeline_textura,
            "texture-single",
            malha,
            imagens_pil[0],
            **kwargs,
        )
    except TypeError as exc:
        _log.warning(
            "Textura single-view recusou texture_resolution; tentando baseline: %s",
            exc,
        )
        resultado = _pipeline_textura(malha, imagens_pil[0])
    return _normalizar_resultado_pipeline(resultado, "texture-single")
