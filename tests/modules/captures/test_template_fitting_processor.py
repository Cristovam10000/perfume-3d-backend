from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.processor import (
    ProcessingError,
    ProcessingInput,
    TemplateFittingProcessor,
)
from app.modules.captures.template_fitting import (
    SilhouetteMetrics,
    TemplateFitAnalyzer,
    TemplateFitPlan,
    TemplateFittingError,
)


def _minimal_glb() -> bytes:
    json_bytes = b'{"asset":{"version":"2.0"}}  '
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_data = b"\x00\x00\x00\x00"
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


class StubAnalyzer:
    def __init__(self, plan: TemplateFitPlan | None = None, error: Exception | None = None):
        self.plan = plan
        self.error = error
        self.calls: list[dict] = []

    async def analyze(self, image_paths, work_dir, **kwargs):
        self.calls.append(
            {
                "image_paths": image_paths,
                "work_dir": work_dir,
                **kwargs,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.plan is not None
        return self.plan


def _make_metrics(tmp_path: Path) -> SilhouetteMetrics:
    mask = tmp_path / "mask.png"
    mask.write_bytes(b"fake-mask")
    return SilhouetteMetrics(
        source_image=tmp_path / "front.jpg",
        mask_path=mask,
        bbox=(10, 20, 120, 300),
        aspect_ratio=0.40,
        fill_ratio=0.55,
        cap_width_ratio=0.65,
        shoulder_width_ratio=0.92,
        waist_width_ratio=0.88,
        cap_height_ratio=0.14,
        symmetry_score=0.93,
        confidence=0.84,
    )


def _make_plan(tmp_path: Path, template_id: str = "cylindrical_basic") -> TemplateFitPlan:
    front = tmp_path / "front.jpg"
    label = tmp_path / "label.png"
    top = tmp_path / "top.png"
    front.write_bytes(b"front")
    label.write_bytes(b"label")
    top.write_bytes(b"top")
    return TemplateFitPlan(
        template_id=template_id,
        front_image=front,
        label_image=label,
        top_image=top,
        metrics=_make_metrics(tmp_path),
        body_width_scale=1.12,
        body_depth_scale=1.08,
        height_scale=0.95,
        cap_width_scale=0.82,
        cap_height_ratio=0.14,
        profile_widths=[0.6, 0.7, 0.9, 1.0, 0.8],
    )


def _make_processor(tmp_path: Path, analyzer) -> TemplateFittingProcessor:
    blender = tmp_path / "blender.exe"
    script = tmp_path / "fit_template.py"
    templates = tmp_path / "templates"
    blender.write_text("placeholder")
    script.write_text("# placeholder")
    templates.mkdir()
    (templates / "rectangular_basic.glb").write_bytes(_minimal_glb())
    (templates / "cylindrical_basic.glb").write_bytes(_minimal_glb())
    return TemplateFittingProcessor(
        blender_executable=blender,
        templates_dir=templates,
        script_path=script,
        analyzer=analyzer,
    )


def _make_input(tmp_path: Path, **overrides) -> ProcessingInput:
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"fake-photo")
    defaults = dict(
        job_id="job-fit",
        image_paths=[photo],
        output_path=tmp_path / "models" / "job-fit.glb",
        template_id="rectangular_basic",
        liquid_color="#336699",
    )
    defaults.update(overrides)
    return ProcessingInput(**defaults)


def _make_runner():
    captured: dict[str, list[list[str]]] = {"calls": []}

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        captured["calls"].append(args)
        output = Path(args[args.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(_minimal_glb())
        return 0, b"", b""

    return fake_run, captured


class TestTemplateFittingProcessor:
    @pytest.mark.asyncio
    async def test_passes_fit_args_label_top_and_color(self, tmp_path: Path):
        plan = _make_plan(tmp_path)
        analyzer = StubAnalyzer(plan)
        proc = _make_processor(tmp_path, analyzer)
        run, captured = _make_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            result = await proc.process(_make_input(tmp_path))

        assert result.output_path.exists()
        assert "cylindrical_basic" in result.message
        args = captured["calls"][0]
        assert args[args.index("--template") + 1].endswith("cylindrical_basic.glb")
        assert "--fit-plan" in args
        assert args[args.index("--body-width-scale") + 1] == "1.120000"
        assert args[args.index("--body-depth-scale") + 1] == "1.080000"
        assert args[args.index("--height-scale") + 1] == "0.950000"
        assert args[args.index("--cap-width-scale") + 1] == "0.820000"
        assert "--label-image" in args
        assert "--top-image" in args
        assert args[args.index("--liquid-color") + 1] == "#336699"
        assert (tmp_path / "models" / "job-fit_fit" / "fit_plan.json").exists()

    @pytest.mark.asyncio
    async def test_does_not_pass_default_classifier_hint_unless_configured(
        self, tmp_path: Path
    ):
        analyzer = StubAnalyzer(_make_plan(tmp_path))
        proc = _make_processor(tmp_path, analyzer)
        run, _captured = _make_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(_make_input(tmp_path, template_id="rectangular_basic"))

        assert analyzer.calls[0]["template_hint"] is None

    @pytest.mark.asyncio
    async def test_can_prefer_classifier_hint(self, tmp_path: Path):
        analyzer = StubAnalyzer(_make_plan(tmp_path, template_id="rectangular_basic"))
        proc = _make_processor(tmp_path, analyzer)
        proc.prefer_input_template_id = True
        run, _captured = _make_runner()

        with patch.object(proc, "_run_blender", side_effect=run):
            await proc.process(_make_input(tmp_path, template_id="rectangular_basic"))

        assert analyzer.calls[0]["template_hint"] == "rectangular_basic"

    @pytest.mark.asyncio
    async def test_analyzer_error_becomes_processing_error(self, tmp_path: Path):
        analyzer = StubAnalyzer(error=TemplateFittingError("segmentacao falhou"))
        proc = _make_processor(tmp_path, analyzer)

        with pytest.raises(ProcessingError, match="segmentacao falhou"):
            await proc.process(_make_input(tmp_path))


class TestTemplateFitAnalyzerSelection:
    def test_selects_cylindrical_for_regular_narrow_silhouette(self, tmp_path: Path):
        analyzer = TemplateFitAnalyzer()
        metrics = _make_metrics(tmp_path)

        template_id = analyzer._choose_template_id(
            metrics,
            available_template_ids={"rectangular_basic", "cylindrical_basic"},
            template_hint=None,
        )

        assert template_id == "cylindrical_basic"

    def test_respects_explicit_hint_when_available(self, tmp_path: Path):
        analyzer = TemplateFitAnalyzer()
        metrics = _make_metrics(tmp_path)

        template_id = analyzer._choose_template_id(
            metrics,
            available_template_ids={"rectangular_basic", "cylindrical_basic"},
            template_hint="rectangular_basic",
        )

        assert template_id == "rectangular_basic"
