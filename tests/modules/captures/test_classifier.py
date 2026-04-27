from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.classifier import (
    CLIPClassifier,
    Classifier,
    ClassificationResult,
    DisabledClassifier,
    _open_rgb_image,
)


# -------------------------------------------------- DisabledClassifier


class TestDisabledClassifier:
    def test_is_classifier_subclass(self):
        assert issubclass(DisabledClassifier, Classifier)

    def test_empty_default_raises(self):
        with pytest.raises(ValueError):
            DisabledClassifier(default_template_id="")

    @pytest.mark.asyncio
    async def test_returns_default_for_any_input(self, tmp_path: Path):
        classifier = DisabledClassifier(default_template_id="my_template")
        result = await classifier.classify([tmp_path / "a.jpg"])

        assert isinstance(result, ClassificationResult)
        assert result.template_id == "my_template"
        assert result.confidence == 1.0
        assert result.scores == {"my_template": 1.0}

    @pytest.mark.asyncio
    async def test_returns_default_even_with_empty_image_list(self):
        classifier = DisabledClassifier(default_template_id="x")
        result = await classifier.classify([])
        assert result.template_id == "x"


# ------------------------------------------------------ CLIPClassifier


class TestCLIPClassifier:
    """Testes da lógica de agregação. Mockam `_predict_image` para evitar
    carregar transformers/torch nos testes unitários (~2GB).
    """

    def test_empty_templates_raises(self):
        with pytest.raises(ValueError):
            CLIPClassifier(model_name="any", templates={})

    def test_open_rgb_image_respects_exif_orientation(self, tmp_path: Path):
        from PIL import Image

        img = Image.new("RGB", (12, 8), color=(10, 20, 30))
        exif = Image.Exif()
        exif[274] = 6  # Orientation: rotate 90 degrees clockwise.
        path = tmp_path / "portrait_with_exif.jpg"
        img.save(path, exif=exif)

        opened = _open_rgb_image(path)

        assert opened.size == (8, 12)

    @pytest.mark.asyncio
    async def test_no_images_raises(self):
        c = CLIPClassifier(model_name="any", templates={"a": "desc"})
        with pytest.raises(ValueError):
            await c.classify([])

    @pytest.mark.asyncio
    async def test_picks_template_with_highest_total_probability(self, tmp_path: Path):
        templates = {"rect": "rectangular", "round": "round"}
        c = CLIPClassifier(model_name="any", templates=templates)

        img1 = tmp_path / "1.jpg"
        img2 = tmp_path / "2.jpg"
        img1.write_bytes(b"x")
        img2.write_bytes(b"x")

        # rect ganha em ambas as imagens
        def fake_predict(self, img):
            return [0.8, 0.2]  # rect, round

        with patch.object(CLIPClassifier, "_predict_image", fake_predict):
            result = await c.classify([img1, img2])

        assert result.template_id == "rect"
        # confiança normalizada (0.8+0.8) / (1.0+1.0) = 0.8
        assert result.confidence == pytest.approx(0.8)
        assert sum(result.scores.values()) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_aggregates_votes_across_images(self, tmp_path: Path):
        """Imagem 1 vota A, imagem 2 vota B → maior soma vence."""
        templates = {"a": "ta", "b": "tb"}
        c = CLIPClassifier(model_name="any", templates=templates)

        img1 = tmp_path / "1.jpg"
        img2 = tmp_path / "2.jpg"
        img3 = tmp_path / "3.jpg"
        for p in (img1, img2, img3):
            p.write_bytes(b"x")

        # img1 e img3 votam 'a' fortemente; img2 vota 'b' fracamente
        responses = iter([[0.9, 0.1], [0.4, 0.6], [0.85, 0.15]])

        def fake_predict(self, img):
            return next(responses)

        with patch.object(CLIPClassifier, "_predict_image", fake_predict):
            result = await c.classify([img1, img2, img3])

        # soma a = 0.9+0.4+0.85 = 2.15 > soma b = 0.1+0.6+0.15 = 0.85
        assert result.template_id == "a"

    @pytest.mark.asyncio
    async def test_scores_are_normalized_to_unit_sum(self, tmp_path: Path):
        templates = {"x": "tx", "y": "ty", "z": "tz"}
        c = CLIPClassifier(model_name="any", templates=templates)
        img = tmp_path / "i.jpg"
        img.write_bytes(b"x")

        def fake_predict(self, img):
            return [0.6, 0.3, 0.1]

        with patch.object(CLIPClassifier, "_predict_image", fake_predict):
            result = await c.classify([img])

        assert sum(result.scores.values()) == pytest.approx(1.0)
        assert result.scores["x"] == pytest.approx(0.6)
        assert result.scores["y"] == pytest.approx(0.3)
        assert result.scores["z"] == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_template_ids_preserved_in_scores(self, tmp_path: Path):
        templates = {
            "rectangular_basic": "rect desc",
            "cylindrical_basic": "cyl desc",
        }
        c = CLIPClassifier(model_name="any", templates=templates)
        img = tmp_path / "i.jpg"
        img.write_bytes(b"x")

        def fake_predict(self, img):
            return [0.5, 0.5]

        with patch.object(CLIPClassifier, "_predict_image", fake_predict):
            result = await c.classify([img])

        assert set(result.scores.keys()) == {"rectangular_basic", "cylindrical_basic"}
