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
    # template   = TemplateProcessor (Blender headless customiza GLB, ~5-15s)
    # integrated = IntegratedPipeline (preprocess + rembg + cache CLIP + Hunyuan + refiner + label)
    pipeline_mode: Literal["fake", "template", "integrated"] = "integrated"

    # Se True, em falha do Hunyuan o IntegratedPipeline tenta o TemplateProcessor
    # antes de marcar o job como erro.
    pipeline_fallback_to_template: bool = False

    blender_executable: Path = Field(
        default=Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    )
    templates_dir: Path = Field(default=Path("./assets/templates/normalized"))
    default_template_id: str = "rectangular_basic"

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

    # ---- Stages auxiliares do pipeline IA ----
    image_preprocessor_type: Literal["disabled", "standard"] = "standard"
    background_remover_type: Literal["disabled", "rembg"] = "rembg"
    mesh_cleaner_type: Literal["disabled", "blender"] = "disabled"
    mesh_min_island_ratio: float = 0.0
    mesh_refiner_type: Literal["disabled", "blender"] = "blender"
    label_extractor_type: Literal["disabled", "homography"] = "homography"
    label_upscaler_type: Literal["disabled", "lanczos"] = "lanczos"
    label_projector_type: Literal["disabled", "blender"] = "blender"
    label_front_axis: str = "front_y_neg"
    label_min_confidence: float = 0.3
    label_target_size: int = 2048

    # ---- Legado (compat) ----
    # COLOR_DETECTOR_TYPE so faz sentido em PIPELINE_MODE=template.
    color_detector_type: Literal["disabled", "average"] = "disabled"
    # CLIP_MODEL e mantido como sinonimo de CACHE_EMBEDDING_MODEL (lido se presente).
    clip_model: str = "openai/clip-vit-base-patch32"
    # CLASSIFIER_TYPE e PROCESSOR_TYPE vinham do MVP de templates. Lidos
    # apenas para preservar .env antigos sem quebrar; sao mapeados em
    # apply_legacy_aliases() abaixo.
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

    PROCESSOR_TYPE → PIPELINE_MODE (apenas se o valor for fake/template; valores
    desconhecidos como 'template_fitting' caem para o default 'integrated').
    """
    import logging

    log = logging.getLogger("app.config")
    legacy = (config.processor_type or "").strip().lower()
    if legacy and legacy != config.pipeline_mode:
        if legacy in {"fake", "template"}:
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
                "PROCESSOR_TYPE=%r nao e um valor valido (esperado fake|template|integrated). "
                "Mantendo PIPELINE_MODE=%s.",
                legacy,
                config.pipeline_mode,
            )
    return config


settings = _apply_legacy_aliases(Settings())
