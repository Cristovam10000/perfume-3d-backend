"""Testes do TransparencyClassifier.

Estrategia:
- DisabledTransparencyClassifier: testes diretos, sem torch.
- ClipTransparencyClassifier: mocka `_prob_transparent`/`_ensure_loaded`
  para nao carregar o modelo real (rapido, deterministico).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.captures.transparency_classifier import (
    ClipTransparencyClassifier,
    DisabledTransparencyClassifier,
    TransparencyResult,
)


def _fake_images(tmp_path: Path, n: int = 3) -> list[Path]:
    paths = []
    for i in range(n):
        p = tmp_path / f"foto_{i}.jpg"
        p.write_bytes(b"jpegfake")
        paths.append(p)
    return paths


class TestDisabledTransparencyClassifier:
    @pytest.mark.asyncio
    async def test_returns_unknown(self, tmp_path: Path):
        classifier = DisabledTransparencyClassifier()

        resultado = await classifier.classify(_fake_images(tmp_path))

        assert resultado.transparent is None
        assert resultado.confidence == 0.0
        assert resultado.source == "disabled"

    @pytest.mark.asyncio
    async def test_accepts_empty_list(self, tmp_path: Path):
        classifier = DisabledTransparencyClassifier()

        resultado = await classifier.classify([])

        assert resultado.transparent is None


class TestClipTransparencyClassifier:
    def test_rejects_empty_model_name(self):
        with pytest.raises(ValueError, match="model_name"):
            ClipTransparencyClassifier(model_name="")

    def test_rejects_invalid_threshold(self):
        with pytest.raises(ValueError, match="threshold"):
            ClipTransparencyClassifier(threshold=0.0)
        with pytest.raises(ValueError, match="threshold"):
            ClipTransparencyClassifier(threshold=1.0)

    @pytest.mark.asyncio
    async def test_empty_image_list_raises(self):
        classifier = ClipTransparencyClassifier()
        with pytest.raises(ValueError, match="pelo menos 1 imagem"):
            await classifier.classify([])

    @pytest.mark.asyncio
    async def test_transparent_when_mean_above_threshold(self, tmp_path: Path):
        classifier = ClipTransparencyClassifier(threshold=0.5)
        probs = iter([0.8, 0.7, 0.9])

        with (
            patch.object(classifier, "_ensure_loaded"),
            patch.object(
                classifier, "_prob_transparent", side_effect=lambda _p: next(probs)
            ),
        ):
            resultado = await classifier.classify(_fake_images(tmp_path))

        assert resultado.transparent is True
        assert resultado.confidence == pytest.approx(0.8, abs=1e-6)
        assert resultado.source == "clip"

    @pytest.mark.asyncio
    async def test_opaque_when_mean_below_threshold(self, tmp_path: Path):
        classifier = ClipTransparencyClassifier(threshold=0.5)
        probs = iter([0.2, 0.3, 0.1])

        with (
            patch.object(classifier, "_ensure_loaded"),
            patch.object(
                classifier, "_prob_transparent", side_effect=lambda _p: next(probs)
            ),
        ):
            resultado = await classifier.classify(_fake_images(tmp_path))

        assert resultado.transparent is False
        assert resultado.confidence == pytest.approx(0.2, abs=1e-6)

    @pytest.mark.asyncio
    async def test_invalid_images_are_skipped(self, tmp_path: Path):
        """Fotos que estouram excecao sao ignoradas; a media usa as restantes."""
        classifier = ClipTransparencyClassifier(threshold=0.5)
        imagens = _fake_images(tmp_path, n=3)

        def prob(path: Path) -> float:
            if path.name == "foto_1.jpg":
                raise OSError("imagem corrompida")
            return 0.9

        with (
            patch.object(classifier, "_ensure_loaded"),
            patch.object(classifier, "_prob_transparent", side_effect=prob),
        ):
            resultado = await classifier.classify(imagens)

        assert resultado.transparent is True
        assert resultado.confidence == pytest.approx(0.9, abs=1e-6)

    @pytest.mark.asyncio
    async def test_all_images_invalid_raises(self, tmp_path: Path):
        classifier = ClipTransparencyClassifier()

        with (
            patch.object(classifier, "_ensure_loaded"),
            patch.object(
                classifier,
                "_prob_transparent",
                side_effect=OSError("imagem corrompida"),
            ),
        ):
            with pytest.raises(ValueError, match="Nenhuma imagem valida"):
                await classifier.classify(_fake_images(tmp_path))


class TestTransparencyResult:
    def test_is_frozen(self):
        resultado = TransparencyResult(transparent=True, confidence=0.9, source="clip")
        with pytest.raises(AttributeError):
            resultado.transparent = False  # type: ignore[misc]
