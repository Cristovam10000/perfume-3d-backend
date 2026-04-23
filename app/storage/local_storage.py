from __future__ import annotations

from pathlib import Path

from ..config import settings


class LocalStorage:
    """Gerencia arquivos locais das capturas e dos modelos 3D gerados.

    Estrutura em disco:
        storage_root/
            uploads/<job_id>/<filename>
            models/<job_id>.glb
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.storage_root).resolve()
        self.uploads_dir = self.root / "uploads"
        self.models_dir = self.root / "models"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def job_uploads_dir(self, job_id: str) -> Path:
        path = self.uploads_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_upload(self, job_id: str, filename: str, content: bytes) -> Path:
        safe_name = Path(filename).name or "image.jpg"
        target = self.job_uploads_dir(job_id) / safe_name
        target.write_bytes(content)
        return target

    def model_path(self, job_id: str) -> Path:
        return self.models_dir / f"{job_id}.glb"

    def model_public_path(self, job_id: str) -> str:
        """Caminho relativo servido por StaticFiles em /files."""
        return f"/files/models/{job_id}.glb"


storage = LocalStorage()
