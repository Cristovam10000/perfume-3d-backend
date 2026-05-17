from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.captures.view_router import (
    CARDINAL_VIEWS,
    CLIPViewRouter,
    LabeledViewRouter,
    PositionalViewRouter,
    ViewRouter,
    ViewRoutingResult,
)


def _make_paths(tmp_path: Path, n: int) -> list[Path]:
    paths: list[Path] = []
    for i in range(n):
        p = tmp_path / f"img_{i:02d}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")  # mínimo válido p/ existir
        paths.append(p)
    return paths


# ----------------------------------------------------- PositionalViewRouter


class TestPositionalViewRouter:
    def test_is_router_subclass(self):
        assert issubclass(PositionalViewRouter, ViewRouter)

    @pytest.mark.asyncio
    async def test_returns_images_in_original_order(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 4)
        router = PositionalViewRouter()

        result = await router.route(imgs)

        assert result.ordered == imgs
        assert result.source == "positional"
        assert result.assignments == {
            "front": imgs[0],
            "left": imgs[1],
            "back": imgs[2],
            "right": imgs[3],
        }

    @pytest.mark.asyncio
    async def test_caps_at_six_images(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 10)
        router = PositionalViewRouter()
        result = await router.route(imgs)
        assert len(result.ordered) == 6

    @pytest.mark.asyncio
    async def test_handles_less_than_four_images(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 2)
        router = PositionalViewRouter()
        result = await router.route(imgs)

        assert result.ordered == imgs
        # Assignments só preenche o que cabe
        assert result.assignments == {"front": imgs[0], "left": imgs[1]}

    @pytest.mark.asyncio
    async def test_empty_images_raises(self):
        router = PositionalViewRouter()
        with pytest.raises(ValueError):
            await router.route([])


# -------------------------------------------------------- LabeledViewRouter


class TestLabeledViewRouter:
    def test_is_router_subclass(self):
        assert issubclass(LabeledViewRouter, ViewRouter)

    @pytest.mark.asyncio
    async def test_reorders_to_cardinal_when_all_views_present(
        self, tmp_path: Path
    ):
        imgs = _make_paths(tmp_path, 4)
        # Ordem do upload: back, front, right, left
        hints = ["back", "front", "right", "left"]
        router = LabeledViewRouter()

        result = await router.route(imgs, hints)

        assert result.source == "labeled"
        assert result.ordered == [imgs[1], imgs[3], imgs[0], imgs[2]]
        assert result.assignments["front"] == imgs[1]
        assert result.assignments["left"] == imgs[3]
        assert result.assignments["back"] == imgs[0]
        assert result.assignments["right"] == imgs[2]

    @pytest.mark.asyncio
    async def test_keeps_extras_after_cardinals(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 6)
        hints = ["front", "left", "back", "right", "extra", "extra"]
        router = LabeledViewRouter()

        result = await router.route(imgs, hints)

        assert result.ordered[:4] == imgs[:4]
        assert result.ordered[4:] == imgs[4:6]

    @pytest.mark.asyncio
    async def test_last_label_wins_when_duplicated(self, tmp_path: Path):
        # App permite "refazer" — usuário tira 'front' duas vezes.
        imgs = _make_paths(tmp_path, 5)
        hints = ["front", "left", "back", "right", "front"]
        router = LabeledViewRouter()

        result = await router.route(imgs, hints)

        # Última 'front' (imgs[4]) deve ganhar; a primeira foi "substituída".
        assert result.assignments["front"] == imgs[4]
        # A 'front' antiga não deve aparecer na lista ordenada.
        assert imgs[0] not in result.ordered

    @pytest.mark.asyncio
    async def test_delegates_to_fallback_when_hints_missing(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 4)
        fallback = PositionalViewRouter()
        router = LabeledViewRouter(fallback=fallback)

        result = await router.route(imgs, hints=None)

        assert result.source == "positional"

    @pytest.mark.asyncio
    async def test_delegates_to_fallback_when_cardinal_missing(
        self, tmp_path: Path
    ):
        imgs = _make_paths(tmp_path, 3)
        # 'back' está faltando — deve cair para o fallback.
        hints = ["front", "left", "right"]
        fallback = PositionalViewRouter()
        router = LabeledViewRouter(fallback=fallback)

        result = await router.route(imgs, hints)

        assert result.source == "positional"

    @pytest.mark.asyncio
    async def test_empty_images_raises(self):
        router = LabeledViewRouter()
        with pytest.raises(ValueError):
            await router.route([], hints=["front"])

    @pytest.mark.asyncio
    async def test_case_insensitive_labels(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 4)
        hints = ["FRONT", " Left ", "Back", "RIGHT"]
        router = LabeledViewRouter()

        result = await router.route(imgs, hints)

        assert result.source == "labeled"
        assert result.ordered == imgs


# ----------------------------------------------------------- CLIPViewRouter


class TestCLIPViewRouter:
    """Testes da lógica de roteamento. Mockam `_scores_and_features` para
    evitar carregar transformers/torch nos testes unitários.
    """

    def test_empty_model_name_raises(self):
        with pytest.raises(ValueError):
            CLIPViewRouter(model_name="")

    @pytest.mark.asyncio
    async def test_delegates_to_labeled_when_hints_present(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 4)
        hints = ["front", "left", "back", "right"]
        router = CLIPViewRouter()

        result = await router.route(imgs, hints)

        assert result.source == "labeled"
        assert result.ordered == imgs

    @pytest.mark.asyncio
    async def test_falls_back_with_single_image(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 1)
        router = CLIPViewRouter()

        result = await router.route(imgs)

        assert result.source == "positional"
        assert result.ordered == imgs

    @pytest.mark.asyncio
    async def test_falls_back_on_clip_error(self, tmp_path: Path):
        imgs = _make_paths(tmp_path, 4)
        router = CLIPViewRouter()

        with patch.object(router, "_route_sync", side_effect=RuntimeError("boom")):
            result = await router.route(imgs)

        assert result.source == "positional"
        assert result.ordered == imgs

    @pytest.mark.asyncio
    async def test_clip_routing_picks_front_and_back_by_scores(
        self, tmp_path: Path
    ):
        import numpy as np

        imgs = _make_paths(tmp_path, 4)
        # imgs[0]: vista lateral (front_score baixo, back_score baixo)
        # imgs[1]: front clara — front_score alto
        # imgs[2]: back — back_score alto
        # imgs[3]: outra lateral
        scores_fakes = [
            (0.20, 0.20, np.array([1.0, 0.0, 0.0], dtype=np.float32)),  # 0
            (0.90, 0.05, np.array([0.0, 1.0, 0.0], dtype=np.float32)),  # 1 front
            (0.05, 0.90, np.array([0.0, 0.0, 1.0], dtype=np.float32)),  # 2 back
            (0.20, 0.20, np.array([0.5, 0.5, 0.0], dtype=np.float32)),  # 3
        ]
        router = CLIPViewRouter()

        def fake_scores(path: Path):
            idx = int(path.stem.split("_")[1])
            return scores_fakes[idx]

        with patch.object(router, "_scores_and_features", side_effect=fake_scores):
            with patch.object(router, "_ensure_loaded"):
                result = await router.route(imgs)

        assert result.source == "clip"
        assert result.assignments["front"] == imgs[1]
        assert result.assignments["back"] == imgs[2]
        # Left/right são as duas restantes (0 e 3); a atribuição é arbitrária
        # mas ambas devem estar presentes.
        cardinal_assigned = {
            result.assignments["front"],
            result.assignments["back"],
            result.assignments.get("left"),
            result.assignments.get("right"),
        }
        assert imgs[0] in cardinal_assigned
        assert imgs[3] in cardinal_assigned
        # Ordem final segue [front, left, back, right]
        assert result.ordered[0] == imgs[1]
        assert result.ordered[2] == imgs[2]
        assert result.confidences["front"] == pytest.approx(0.90)
        assert result.confidences["back"] == pytest.approx(0.90)

    @pytest.mark.asyncio
    async def test_clip_routing_handles_extras(self, tmp_path: Path):
        import numpy as np

        imgs = _make_paths(tmp_path, 6)
        scores_fakes = [
            (0.90, 0.05, np.array([1.0, 0.0], dtype=np.float32)),  # 0 front
            (0.10, 0.10, np.array([0.0, 1.0], dtype=np.float32)),  # 1
            (0.10, 0.10, np.array([0.7, 0.7], dtype=np.float32)),  # 2
            (0.05, 0.90, np.array([1.0, 1.0], dtype=np.float32)),  # 3 back
            (0.10, 0.10, np.array([0.3, 0.3], dtype=np.float32)),  # 4 extra
            (0.10, 0.10, np.array([0.6, 0.4], dtype=np.float32)),  # 5 extra
        ]
        router = CLIPViewRouter()

        def fake_scores(path: Path):
            idx = int(path.stem.split("_")[1])
            return scores_fakes[idx]

        with patch.object(router, "_scores_and_features", side_effect=fake_scores):
            with patch.object(router, "_ensure_loaded"):
                result = await router.route(imgs)

        assert result.source == "clip"
        # 4 cardeais + 2 extras = 6 ordenadas
        assert len(result.ordered) == 6
        assert result.assignments["front"] == imgs[0]
        assert result.assignments["back"] == imgs[3]


# --------------------------------------------------------- module-level smoke


def test_cardinal_views_constant():
    assert CARDINAL_VIEWS == ("front", "left", "back", "right")


def test_view_routing_result_defaults():
    r = ViewRoutingResult(ordered=[], assignments={})
    assert r.confidences == {}
    assert r.source == "positional"
