"""Classificadores de forma do frasco a partir das imagens enviadas.

A motivação: o `TemplateProcessor` precisa saber qual `template_id` usar
para customizar (rectangular, cylindrical, ...). Em vez de pedir ao usuário
no app, classificamos automaticamente a partir das fotos.

Mesmo padrão Strategy do `Processor`: uma ABC `Classifier` com várias
implementações trocáveis por configuração.

Implementações disponíveis:
- `DisabledClassifier`: sempre devolve um `template_id` fixo (zero deps).
- `CLIPClassifier`: usa OpenAI CLIP via Hugging Face transformers.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.classifier")


@dataclass(frozen=True)
class ClassificationResult:
    template_id: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)


class Classifier(ABC):
    """Contrato abstrato dos classificadores de forma."""

    @abstractmethod
    async def classify(self, images: list[Path]) -> ClassificationResult: ...


class DisabledClassifier(Classifier):
    """Bypass: devolve sempre o `default_template_id`.

    Útil quando o CLIP/transformers não estão instalados, em testes, ou para
    desenvolvimento rápido sem GPU.
    """

    def __init__(self, default_template_id: str):
        if not default_template_id:
            raise ValueError("default_template_id não pode ser vazio")
        self.default_template_id = default_template_id

    async def classify(self, images: list[Path]) -> ClassificationResult:
        return ClassificationResult(
            template_id=self.default_template_id,
            confidence=1.0,
            scores={self.default_template_id: 1.0},
        )


class CLIPClassifier(Classifier):
    """Classifica forma usando OpenAI CLIP (zero-shot via texto).

    Estratégia:
    1. Para cada imagem da entrada, pede ao CLIP a probabilidade de cada
       descrição de template.
    2. Soma as probabilidades por template ao longo de todas as imagens
       (votação ponderada — robusto contra fotos isoladas que confundam).
    3. Normaliza pela soma total e devolve o template vencedor.

    O modelo é carregado preguiçosamente na primeira classificação, e a
    inferência roda em thread executor (`asyncio.to_thread`) para não
    bloquear o event loop do FastAPI.
    """

    def __init__(
        self,
        model_name: str,
        templates: dict[str, str],
    ):
        if not templates:
            raise ValueError(
                "CLIPClassifier precisa de pelo menos 1 template no mapping"
            )
        self.model_name = model_name
        self.templates = dict(templates)
        self._template_ids = list(self.templates.keys())
        self._descriptions = list(self.templates.values())
        self._model = None
        self._processor = None

    async def classify(self, images: list[Path]) -> ClassificationResult:
        if not images:
            raise ValueError("CLIPClassifier precisa de pelo menos 1 imagem")
        return await asyncio.to_thread(self._classify_sync, images)

    # ------------------------------------------------------------------ sync

    def _classify_sync(self, images: list[Path]) -> ClassificationResult:
        votes = {tid: 0.0 for tid in self._template_ids}

        for img_path in images:
            probs = self._predict_image(img_path)
            for i, prob in enumerate(probs):
                votes[self._template_ids[i]] += prob

        total = sum(votes.values())
        if total > 0:
            votes = {k: v / total for k, v in votes.items()}

        winner = max(votes, key=lambda k: votes[k])
        confidence = votes[winner]

        _log.info(
            "Classificacao: %s (%.2f%%) entre %d candidatos, %d imagens",
            winner,
            confidence * 100,
            len(self._template_ids),
            len(images),
        )
        return ClassificationResult(
            template_id=winner,
            confidence=confidence,
            scores=votes,
        )

    def _predict_image(self, img_path: Path) -> list[float]:
        """Roda CLIP em uma imagem; devolve lista de probabilidades por template."""
        self._ensure_loaded()

        img = _open_rgb_image(img_path)
        inputs = self._processor(
            text=self._descriptions,
            images=img,
            return_tensors="pt",
            padding=True,
        )
        outputs = self._model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)[0]
        # detach + tolist evita o warning sobre tensor com requires_grad=True.
        return probs.detach().tolist()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        # Imports lazy: assim o modulo importa mesmo sem torch instalado.
        from transformers import CLIPModel, CLIPProcessor

        _log.info("Carregando CLIP '%s'...", self.model_name)
        self._model = CLIPModel.from_pretrained(self.model_name)
        self._processor = CLIPProcessor.from_pretrained(self.model_name)


def _open_rgb_image(path: Path):
    """Abre uma imagem respeitando orientação EXIF antes de enviar ao CLIP."""
    from PIL import Image, ImageOps  # imports preguiçosos

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
