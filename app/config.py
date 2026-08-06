from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "perfume-3d-backend"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5433/tcc"
    )

    storage_root: Path = Field(default=Path("./storage"))

    cors_origins: str = "*"

    # ---- Pipeline 3D ----
    # fake       = FakeProcessor (cubo sintetico, ~3s, sem deps externas)
    # integrated = IntegratedPipeline (preprocess + rembg + cache CLIP + Hunyuan + refiner + label)
    pipeline_mode: Literal["fake", "integrated"] = "integrated"

    blender_executable: Path = Field(
        default=Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    )

    # ---- Hunyuan3D-2mv (cliente HTTP) ----
    hunyuan_url: str = "http://localhost:7860"
    hunyuan_timeout_seconds: float = 1200.0
    hunyuan_octree_resolution: int = 384
    hunyuan_num_inference_steps: int = 75
    hunyuan_guidance_scale: float = 7.5
    hunyuan_mc_algo: str = "mc"
    hunyuan_texture_resolution: int = 2048

    # ---- Cache de modelos (similaridade CLIP) ----
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.92
    cache_embedder_type: Literal["disabled", "clip"] = "clip"
    cache_embedding_model: str = "openai/clip-vit-base-patch32"

    # ---- View router (rotulagem de vistas pro Hunyuan3D-2mv) ----
    # positional = ordem do upload vira front/left/back/right (legado).
    # clip       = CLIPViewRouter zero-shot (front/back) + embeddings (left/right).
    # Em ambos os modos, se o cliente enviar labels via campo `views` do POST
    # /captures, eles têm prioridade (LabeledViewRouter).
    view_router_type: Literal["positional", "clip"] = "clip"

    # ---- Stages auxiliares do pipeline IA ----
    image_preprocessor_type: Literal["disabled", "standard"] = "standard"
    background_remover_type: Literal["disabled", "rembg"] = "rembg"
    # Modelo do rembg. `birefnet-general` é estado-da-arte para objetos
    # gerais (vidro/transparência) — baixa ~885MB no primeiro uso.
    # `isnet-general-use` é mais leve (~178MB) e suficiente pra fotos
    # comuns. `u2net` é o default histórico do rembg (qualidade menor).
    background_remover_model: str = "isnet-general-use"
    mesh_refiner_type: Literal["disabled", "blender"] = "blender"
    # Classifica o frasco como transparente/opaco (CLIP zero-shot) para o
    # refiner decidir entre shader de vidro e preservar a textura do corpo.
    # disabled = refiner usa heuristica legada (`auto`).
    transparency_classifier_type: Literal["disabled", "clip"] = "clip"
    # Probabilidade media minima do ensemble "transparente" para aplicar
    # vidro. Calibrado em fotos reais: vidro translucido escuro ~0.41-0.49,
    # frascos opacos <=0.10 — 0.30 separa com margem dos dois lados.
    transparency_threshold: float = 0.30
    label_extractor_type: Literal["disabled", "homography"] = "homography"
    label_upscaler_type: Literal["disabled", "lanczos"] = "lanczos"
    label_projector_type: Literal["disabled", "blender"] = "blender"
    label_front_axis: str = "front_y_neg"
    label_min_confidence: float = 0.3
    label_target_size: int = 2048

    # Projeta a foto do topo na tampa. O Hunyuan nao reconstroi o topo (as 4
    # vistas cardeais nao o enxergam) e entrega um disco liso sem textura.
    # So dispara quando o app rotula uma foto como `top` no POST /captures.
    top_projector_type: Literal["disabled", "blender"] = "blender"
    # Cosseno minimo entre a normal da face e o eixo Z para a face contar como
    # "topo". 0.45 aceita a curvatura do ombro da tampa sem pegar as laterais.
    top_cosine_threshold: float = 0.45
    # Elongacao maxima (razao entre eixos principais da silhueta) para uma foto
    # ser aceita como vista de topo. Medido nas 34 fotos reais do projeto: topo
    # correto 1.03, topo obliquo 2.06, cardeais 1.50-4.23. Ver top_photo_check.
    top_elongation_max: float = 1.35

    # Projeta a foto das costas nas faces traseiras do corpo. O Hunyuan gera a
    # geometria com 4 vistas mas textura com UMA (o pipeline de paint recusa
    # lista); as outras vistas sao sintetizadas a partir da foto da frente, o
    # que faz o verso do frasco sair inventado. Ver docs/16.
    back_projector_type: Literal["disabled", "blender"] = "blender"
    back_cosine_threshold: float = 0.45

    # Comprime o GLB final com Draco (KHR_draco_mesh_compression). Medido em
    # 5,5x no job 15ef21e9: 77,1 MB -> 13,9 MB, sem perda visivel. Desligue
    # apenas se algum cliente nao conseguir decodificar Draco — o app nao e o
    # caso, ver `draco/` servido em /files e DRACO_DECODER_PATH no front.
    glb_optimizer_type: Literal["disabled", "blender"] = "blender"
    # Bits por eixo na quantizacao de posicao. 14 = 16.384 passos no maior eixo
    # (~6 micrometros num frasco de 10 cm), bem abaixo do que a malha resolve.
    glb_position_quantization: int = 14
    glb_texcoord_quantization: int = 12

    # Renderiza o PNG do card do produto a partir do GLB final. Preenche
    # `modelos_3d_produto.caminho_imagem_preview`, que existia no schema e
    # nunca era escrita — por isso o card caia num gradiente generico.
    preview_renderer_type: Literal["disabled", "blender"] = "blender"
    preview_resolution: int = 512

    # ---- Legado (compat) ----
    # COLOR_DETECTOR_TYPE servia ao TemplateProcessor (removido). Mantido
    # apenas para nao quebrar .env antigos; nao e lido por nenhum stage.
    color_detector_type: Literal["disabled", "average"] = "disabled"
    # CLIP_MODEL e mantido como sinonimo de CACHE_EMBEDDING_MODEL (lido se presente).
    clip_model: str = "openai/clip-vit-base-patch32"
    # CLASSIFIER_TYPE e PROCESSOR_TYPE vinham do MVP de templates. O
    # Classifier foi removido junto com o TemplateProcessor; as chaves ficam
    # apenas para nao quebrar .env antigos (PROCESSOR_TYPE ainda e mapeado em
    # _apply_legacy_aliases; CLASSIFIER_TYPE nao e lido por nenhum stage).
    classifier_type: Literal["disabled", "clip"] = "disabled"
    processor_type: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.storage_root / "models"

    @property
    def cache_dir(self) -> Path:
        return self.storage_root / "cache"


def _apply_legacy_aliases(config: Settings) -> Settings:
    """Mapeia chaves antigas do .env para os nomes novos com warning.

    PROCESSOR_TYPE → PIPELINE_MODE (apenas se o valor for fake/integrated).
    Valores desconhecidos — incluindo 'template', removido junto com o
    TemplateProcessor — caem para o default 'integrated'.
    """
    import logging

    log = logging.getLogger("app.config")
    legacy = (config.processor_type or "").strip().lower()
    if legacy and legacy != config.pipeline_mode:
        if legacy == "fake":
            log.warning(
                "PROCESSOR_TYPE=%r esta depreciado; renomeie para PIPELINE_MODE no .env. "
                "Aplicando %s.",
                legacy,
                legacy,
            )
            config.pipeline_mode = legacy  # type: ignore[assignment]
        elif legacy == "integrated":
            config.pipeline_mode = "integrated"
        else:
            log.warning(
                "PROCESSOR_TYPE=%r nao e um valor valido (esperado fake|integrated). "
                "Mantendo PIPELINE_MODE=%s.",
                legacy,
                config.pipeline_mode,
            )
    return config


settings = _apply_legacy_aliases(Settings())
