"""Geração de dataset sintético: renderiza N vistas cardeais de um GLB.

Pega um GLB de referência (ex: um template de `assets/templates/normalized/`)
e produz 4 PNGs (`front.png`, `left.png`, `back.png`, `right.png`) que servem
como entrada para cada pipeline de reconstrução 3D. Como conhecemos o GLB
original, ele vira **ground truth** para as métricas geométricas.

Internamente chama o Blender headless (`render_cardinal_views.py`), mesmo
padrão do `MeshCleaner` / `MeshRefiner` do pipeline principal — assim
reaproveitamos o mesmo executável já configurado em `BLENDER_EXECUTABLE`.

Uso típico:

    from eval.synthetic_dataset import render_synthetic_views

    result = render_synthetic_views(
        glb_path=Path("assets/templates/normalized/feeling_rectangular_blue.glb"),
        output_dir=Path("eval_outputs/synthetic/feeling_blue/"),
        blender_executable=Path("C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"),
    )
    # result.views = {"front": Path("...front.png"), ...}
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.core.logging import get_logger

_log = get_logger("eval.synthetic_dataset")

CARDINAL_VIEWS = ("front", "left", "back", "right")

_DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent / "blender_scripts" / "render_cardinal_views.py"
)
_DEFAULT_BLENDER_EXECUTABLE = Path(
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)


@dataclass(frozen=True)
class SyntheticRenderResult:
    """Resultado da renderização de um GLB de referência.

    `views` mapeia o rótulo cardeal → caminho do PNG renderizado.
    Sempre contém as 4 chaves de `CARDINAL_VIEWS` quando bem-sucedido.
    """

    glb_source: Path
    output_dir: Path
    views: Mapping[str, Path]


class SyntheticRenderError(Exception):
    """Falha ao renderizar vistas sintéticas via Blender."""


def render_synthetic_views(
    glb_path: Path,
    output_dir: Path,
    *,
    blender_executable: Path = _DEFAULT_BLENDER_EXECUTABLE,
    script_path: Path = _DEFAULT_SCRIPT_PATH,
    resolution: int = 1024,
    rotate_z_deg: float = 0.0,
    bg_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    timeout_seconds: float = 300.0,
) -> SyntheticRenderResult:
    """Renderiza as 4 vistas cardeais de um GLB usando Blender headless.

    Args:
        glb_path: GLB de referência (ground truth).
        output_dir: diretório que receberá os PNGs `{front,left,back,right}.png`.
        blender_executable: caminho do binário do Blender.
        script_path: script Python do Blender (default: o vendado neste módulo).
        resolution: tamanho do PNG (quadrado).
        rotate_z_deg: rotação prévia ao redor de Z, quando o GLB não está
            orientado com a frente em +Y (Blender convention).
        bg_color: cor de fundo (RGB 0-1) da render.
        timeout_seconds: aborta se a render demorar mais que isso.

    Raises:
        FileNotFoundError: GLB, script ou executável ausentes.
        SyntheticRenderError: Blender retornou falha ou PNGs não foram criados.
    """
    if not glb_path.exists():
        raise FileNotFoundError(f"GLB não encontrado: {glb_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"Script Blender não encontrado: {script_path}")
    if not Path(blender_executable).exists():
        raise FileNotFoundError(
            f"Executável do Blender não encontrado: {blender_executable}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(blender_executable),
        "--background",
        "--python",
        str(script_path),
        "--",
        "--input",
        str(glb_path),
        "--output-dir",
        str(output_dir),
        "--resolution",
        str(resolution),
        "--rotate-z",
        str(rotate_z_deg),
        "--bg-color",
        ",".join(f"{c:.4f}" for c in bg_color),
    ]
    _log.info("Renderizando vistas sintéticas: %s → %s", glb_path.name, output_dir)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyntheticRenderError(
            f"Render do Blender excedeu {timeout_seconds}s para {glb_path.name}"
        ) from exc

    if proc.returncode != 0:
        raise SyntheticRenderError(
            f"Blender saiu com código {proc.returncode}. "
            f"stderr (últimas 500 chars): {proc.stderr[-500:]!r}"
        )

    views: dict[str, Path] = {}
    faltando: list[str] = []
    for name in CARDINAL_VIEWS:
        png = output_dir / f"{name}.png"
        if png.exists():
            views[name] = png
        else:
            faltando.append(name)

    if faltando:
        raise SyntheticRenderError(
            f"Vistas não geradas: {faltando}. "
            f"stdout (últimas 500 chars): {proc.stdout[-500:]!r}"
        )

    _log.info("Renderização concluída: %d vistas em %s", len(views), output_dir)
    return SyntheticRenderResult(
        glb_source=glb_path,
        output_dir=output_dir,
        views=views,
    )
