from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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

    # ---- Pipeline 3D (Blender / TemplateProcessor) ----
    # 'fake' = FakeProcessor (cubo sintetico, ~3s, sem deps externas).
    # 'template' = TemplateProcessor (Blender headless customiza GLB, ~5-15s).
    processor_type: Literal["fake", "template"] = "fake"

    blender_executable: Path = Field(
        default=Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    )
    templates_dir: Path = Field(default=Path("./assets/templates/normalized"))

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


settings = Settings()
