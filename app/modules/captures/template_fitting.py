"""Silhouette-based fitting helpers for template GLB generation.

This module keeps the computer-vision part outside `processor.py`:

1. pick the best front/top images from the uploaded set;
2. segment the bottle with a deterministic background-color heuristic;
3. estimate silhouette proportions;
4. pick a template when no reliable external classifier is enabled;
5. emit a fitting plan consumed by Blender.

The heavy image dependencies are lazy imports so the backend still boots in
the default fake/template modes without Pillow/Numpy installed.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ...core.logging import get_logger

_log = get_logger("captures.template_fitting")


class TemplateFittingError(Exception):
    """Raised when silhouette fitting cannot be computed."""


@dataclass(frozen=True)
class SilhouetteMetrics:
    source_image: Path
    mask_path: Path
    bbox: tuple[int, int, int, int]
    aspect_ratio: float
    fill_ratio: float
    cap_width_ratio: float
    shoulder_width_ratio: float
    waist_width_ratio: float
    cap_height_ratio: float
    symmetry_score: float
    confidence: float


@dataclass(frozen=True)
class TemplateFitPlan:
    template_id: str
    front_image: Path
    label_image: Path | None
    top_image: Path | None
    metrics: SilhouetteMetrics
    body_width_scale: float
    body_depth_scale: float
    height_scale: float
    cap_width_scale: float
    cap_height_ratio: float
    profile_widths: list[float]

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["front_image"] = str(self.front_image)
        payload["label_image"] = str(self.label_image) if self.label_image else None
        payload["top_image"] = str(self.top_image) if self.top_image else None
        payload["metrics"]["source_image"] = str(self.metrics.source_image)
        payload["metrics"]["mask_path"] = str(self.metrics.mask_path)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class TemplateFitAnalyzer:
    """Builds a Blender fitting plan from product photos.

    The segmentation intentionally uses classical CV heuristics instead of a
    model download. It works best with centered product photos on a reasonably
    uniform background. For noisy real-world backgrounds, this class is the
    integration point where a stronger segmenter such as rembg/SAM can be
    plugged in later.
    """

    def __init__(
        self,
        *,
        default_template_id: str = "rectangular_basic",
        min_mask_coverage: float = 0.01,
        max_mask_coverage: float = 0.85,
    ):
        if not default_template_id:
            raise ValueError("default_template_id cannot be empty")
        self.default_template_id = default_template_id
        self.min_mask_coverage = min_mask_coverage
        self.max_mask_coverage = max_mask_coverage

    async def analyze(
        self,
        image_paths: list[Path],
        work_dir: Path,
        *,
        available_template_ids: Iterable[str],
        template_hint: str | None = None,
        explicit_label_image: Path | None = None,
    ) -> TemplateFitPlan:
        if not image_paths:
            raise TemplateFittingError("Template fitting precisa de pelo menos 1 imagem")

        work_dir.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(
            self._analyze_sync,
            image_paths,
            work_dir,
            set(available_template_ids),
            template_hint,
            explicit_label_image,
        )

    # ------------------------------------------------------------------ sync

    def _analyze_sync(
        self,
        image_paths: list[Path],
        work_dir: Path,
        available_template_ids: set[str],
        template_hint: str | None,
        explicit_label_image: Path | None,
    ) -> TemplateFitPlan:
        front_image = _pick_front_image(image_paths)
        top_image = _pick_top_image(image_paths, front_image)

        rgb, image_size = _load_rgb_array(front_image)
        mask = self._segment_foreground(rgb)
        mask_path = work_dir / "silhouette_mask.png"
        _save_mask(mask, mask_path)

        metrics = self._measure(front_image, mask_path, mask, image_size)
        template_id = self._choose_template_id(
            metrics,
            available_template_ids=available_template_ids,
            template_hint=template_hint,
        )
        label_image = explicit_label_image
        if label_image is None:
            label_image = self._extract_label_candidate(
                front_image,
                metrics,
                work_dir / "label_candidate.png",
            )

        top_candidate = None
        if top_image is not None:
            top_candidate = _normalize_image_to_png(
                top_image,
                work_dir / "top_candidate.png",
            )

        plan = self._build_plan(
            template_id=template_id,
            front_image=front_image,
            label_image=label_image,
            top_image=top_candidate,
            metrics=metrics,
        )
        _log.info(
            "Template fitting: template=%s aspect=%.3f confidence=%.2f",
            plan.template_id,
            metrics.aspect_ratio,
            metrics.confidence,
        )
        return plan

    # ---------------------------------------------------------------- metrics

    def _segment_foreground(self, rgb):
        """Segment foreground by distance from the median border color."""
        import numpy as np

        h, w = rgb.shape[:2]
        border_size = max(2, int(round(min(h, w) * 0.04)))
        border = np.concatenate(
            [
                rgb[:border_size, :, :].reshape(-1, 3),
                rgb[-border_size:, :, :].reshape(-1, 3),
                rgb[:, :border_size, :].reshape(-1, 3),
                rgb[:, -border_size:, :].reshape(-1, 3),
            ],
            axis=0,
        ).astype(np.float32)

        background = np.median(border, axis=0)
        dist = np.linalg.norm(rgb.astype(np.float32) - background, axis=2)
        border_dist = np.linalg.norm(border - background, axis=1)
        threshold = max(28.0, float(np.percentile(border_dist, 95)) + 14.0)
        mask = dist > threshold
        mask = _clean_mask(mask)

        coverage = float(np.count_nonzero(mask)) / float(h * w)
        if coverage < self.min_mask_coverage or coverage > self.max_mask_coverage:
            raise TemplateFittingError(
                "Nao foi possivel segmentar a silhueta do frasco "
                f"(coverage={coverage:.3f}). Use fundo mais uniforme ou ative "
                "um segmentador dedicado."
            )
        return mask

    def _measure(
        self,
        source_image: Path,
        mask_path: Path,
        mask,
        image_size: tuple[int, int],
    ) -> SilhouetteMetrics:
        import numpy as np

        ys, xs = np.where(mask)
        if len(xs) == 0 or len(ys) == 0:
            raise TemplateFittingError("Mascara de silhueta vazia")

        x_min, x_max = int(xs.min()), int(xs.max())
        y_min, y_max = int(ys.min()), int(ys.max())
        bbox_w = max(1, x_max - x_min + 1)
        bbox_h = max(1, y_max - y_min + 1)
        crop = mask[y_min : y_max + 1, x_min : x_max + 1]
        row_widths = crop.sum(axis=1).astype(float)
        max_width = max(float(row_widths.max()), 1.0)

        aspect_ratio = bbox_w / bbox_h
        fill_ratio = float(np.count_nonzero(crop)) / float(bbox_w * bbox_h)
        cap_width_ratio = _median_row_width(row_widths, 0.00, 0.16) / max_width
        shoulder_width_ratio = _median_row_width(row_widths, 0.18, 0.36) / max_width
        waist_width_ratio = _median_row_width(row_widths, 0.48, 0.74) / max_width
        cap_height_ratio = _estimate_cap_height_ratio(row_widths)
        symmetry_score = _estimate_symmetry(crop)

        image_w, image_h = image_size
        bbox_coverage = (bbox_w * bbox_h) / float(max(image_w * image_h, 1))
        confidence = _clamp(
            0.25
            + (0.35 * min(1.0, fill_ratio / 0.55))
            + (0.25 * symmetry_score)
            + (0.15 * min(1.0, bbox_coverage / 0.55)),
            0.0,
            1.0,
        )

        return SilhouetteMetrics(
            source_image=source_image,
            mask_path=mask_path,
            bbox=(x_min, y_min, bbox_w, bbox_h),
            aspect_ratio=aspect_ratio,
            fill_ratio=fill_ratio,
            cap_width_ratio=cap_width_ratio,
            shoulder_width_ratio=shoulder_width_ratio,
            waist_width_ratio=waist_width_ratio,
            cap_height_ratio=cap_height_ratio,
            symmetry_score=symmetry_score,
            confidence=confidence,
        )

    def _choose_template_id(
        self,
        metrics: SilhouetteMetrics,
        *,
        available_template_ids: set[str],
        template_hint: str | None,
    ) -> str:
        if template_hint and template_hint in available_template_ids:
            return template_hint

        def first_available(*ids: str) -> str:
            for template_id in ids:
                if template_id in available_template_ids:
                    return template_id
            if self.default_template_id in available_template_ids:
                return self.default_template_id
            return sorted(available_template_ids)[0] if available_template_ids else self.default_template_id

        aspect = metrics.aspect_ratio
        width_variation = abs(metrics.shoulder_width_ratio - metrics.waist_width_ratio)

        if aspect >= 0.72:
            if metrics.fill_ratio >= 0.66:
                return first_available("round_spherical", "square_compact")
            return first_available("square_compact", "round_spherical")

        if aspect <= 0.34:
            return first_available("feeling_rectangular_blue", "rectangular_basic")

        if width_variation <= 0.10 and aspect <= 0.58:
            return first_available("cylindrical_basic", "rectangular_basic")

        if aspect <= 0.54:
            return first_available("rectangular_basic", "feeling_rectangular_blue")

        return first_available("ornamental_modernist", "rectangular_basic")

    def _build_plan(
        self,
        *,
        template_id: str,
        front_image: Path,
        label_image: Path | None,
        top_image: Path | None,
        metrics: SilhouetteMetrics,
    ) -> TemplateFitPlan:
        base_aspect = {
            "feeling_rectangular_blue": 0.34,
            "rectangular_basic": 0.46,
            "cylindrical_basic": 0.43,
            "square_compact": 0.82,
            "round_spherical": 0.92,
            "ornamental_modernist": 0.62,
        }.get(template_id, 0.46)

        body_width_scale = _clamp(metrics.aspect_ratio / base_aspect, 0.58, 1.65)
        height_scale = _clamp(base_aspect / max(metrics.aspect_ratio, 1e-6), 0.82, 1.24)

        if template_id in {"cylindrical_basic", "round_spherical"}:
            body_depth_scale = body_width_scale
        else:
            body_depth_scale = _clamp(body_width_scale * 0.72, 0.50, 1.25)

        cap_width_scale = _clamp(
            metrics.cap_width_ratio / max(metrics.shoulder_width_ratio, 0.20),
            0.58,
            1.42,
        )

        return TemplateFitPlan(
            template_id=template_id,
            front_image=front_image,
            label_image=label_image,
            top_image=top_image,
            metrics=metrics,
            body_width_scale=body_width_scale,
            body_depth_scale=body_depth_scale,
            height_scale=height_scale,
            cap_width_scale=cap_width_scale,
            cap_height_ratio=_clamp(metrics.cap_height_ratio, 0.08, 0.32),
            profile_widths=_sample_profile_widths(metrics.mask_path, samples=32),
        )

    def _extract_label_candidate(
        self,
        image_path: Path,
        metrics: SilhouetteMetrics,
        output_path: Path,
    ) -> Path | None:
        from PIL import Image, ImageOps

        x, y, w, h = metrics.bbox
        left = int(round(x + w * 0.20))
        right = int(round(x + w * 0.80))
        top = int(round(y + h * 0.34))
        bottom = int(round(y + h * 0.76))
        if right - left < 20 or bottom - top < 20:
            return None

        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGBA")
            crop = img.crop((left, top, right, bottom))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            crop.save(output_path, format="PNG")
        return output_path


def _pick_front_image(paths: list[Path]) -> Path:
    ranked = sorted(
        paths,
        key=lambda p: (
            0 if any(token in p.stem.lower() for token in ("front", "frente", "01")) else 1,
            p.name.lower(),
        ),
    )
    return ranked[0]


def _pick_top_image(paths: list[Path], front_image: Path) -> Path | None:
    for path in paths:
        stem = path.stem.lower()
        if path != front_image and any(token in stem for token in ("top", "tampa", "cima")):
            return path
    return None


def _load_rgb_array(path: Path):
    try:
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise TemplateFittingError(
            "Template fitting requer Pillow e Numpy. Instale as dependencias "
            "opcionais com: pip install -r requirements-vision.txt"
        ) from exc

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        return np.array(img), img.size


def _normalize_image_to_png(input_path: Path, output_path: Path) -> Path:
    from PIL import Image, ImageOps

    with Image.open(input_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGBA")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="PNG")
    return output_path


def _save_mask(mask, output_path: Path) -> None:
    import numpy as np
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mask_img = (mask.astype(np.uint8) * 255)
    Image.fromarray(mask_img, mode="L").save(output_path)


def _sample_profile_widths(mask_path: Path, samples: int) -> list[float]:
    """Returns normalized row widths from top to bottom of the silhouette."""
    import numpy as np
    from PIL import Image

    img = Image.open(mask_path).convert("L")
    arr = np.array(img) > 127
    ys, xs = np.where(arr)
    if len(xs) == 0 or len(ys) == 0:
        return [1.0 for _ in range(samples)]

    y_min, y_max = int(ys.min()), int(ys.max())
    crop = arr[y_min : y_max + 1, :]
    row_widths = crop.sum(axis=1).astype(float)
    max_width = max(float(row_widths.max()), 1.0)

    profile: list[float] = []
    for index in range(samples):
        y = round(index * (len(row_widths) - 1) / max(samples - 1, 1))
        profile.append(_clamp(float(row_widths[y]) / max_width, 0.05, 1.0))

    return _smooth_profile(profile)


def _smooth_profile(profile: list[float]) -> list[float]:
    if len(profile) < 3:
        return profile
    smoothed: list[float] = []
    for index, value in enumerate(profile):
        left = profile[max(0, index - 1)]
        right = profile[min(len(profile) - 1, index + 1)]
        smoothed.append((left + value * 2.0 + right) / 4.0)
    return smoothed


def _clean_mask(mask):
    """Use OpenCV cleanup when available, otherwise return the raw mask."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return mask

    mask_u8 = mask.astype("uint8") * 255
    kernel = np.ones((5, 5), dtype="uint8")
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel, iterations=1)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask_u8, 8)
    if count <= 1:
        return mask_u8 > 0

    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


def _median_row_width(row_widths, start: float, end: float) -> float:
    import numpy as np

    n = len(row_widths)
    i0 = int(math.floor(n * start))
    i1 = max(i0 + 1, int(math.ceil(n * end)))
    segment = row_widths[i0:i1]
    segment = segment[segment > 0]
    if len(segment) == 0:
        return 0.0
    return float(np.median(segment))


def _estimate_cap_height_ratio(row_widths) -> float:
    import numpy as np

    max_width = max(float(row_widths.max()), 1.0)
    threshold = max_width * 0.68
    for idx, width in enumerate(row_widths):
        if width >= threshold:
            return _clamp(idx / max(len(row_widths), 1), 0.08, 0.32)
    non_empty = np.where(row_widths > 0)[0]
    if len(non_empty) == 0:
        return 0.16
    return _clamp(float(non_empty[0]) / max(len(row_widths), 1), 0.08, 0.32)


def _estimate_symmetry(crop) -> float:
    import numpy as np

    h, w = crop.shape[:2]
    center = (w - 1) / 2.0
    scores = []
    for y in range(h):
        xs = np.where(crop[y])[0]
        if len(xs) < 2:
            continue
        left = center - float(xs.min())
        right = float(xs.max()) - center
        denom = max(left, right, 1.0)
        scores.append(1.0 - min(1.0, abs(left - right) / denom))
    if not scores:
        return 0.0
    return _clamp(float(np.mean(scores)), 0.0, 1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
