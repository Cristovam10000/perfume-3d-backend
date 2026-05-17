"""Roteamento de vistas (front/left/back/right) para o Hunyuan3D-2mv.

Motivação: o Hunyuan-2mv foi treinado esperando um dict ordenado
`{"front": ..., "left": ..., "back": ..., "right": ...}`. O servidor do
Hunyuan (`docker/hunyuan/server.py`) mapeia POSICIONALMENTE — a primeira
imagem recebida vira "front", a segunda "left", etc. Sem nenhuma garantia
que a ordem do upload corresponda ao ângulo real, o modelo recebia
"front" como uma vista 3/4 aleatória e gerava reconstruções ruins.

Este módulo resolve o problema rotulando explicitamente cada foto antes
de enviá-la ao Hunyuan, devolvendo a lista **reordenada** para que a
posição no upload bata com o ângulo real.

Mesmo padrão Strategy do resto do módulo:
- `PositionalViewRouter`: bypass que confia na ordem original (legado).
- `LabeledViewRouter`: usa labels enviados pelo cliente (app guiado).
- `CLIPViewRouter`: zero-shot CLIP para classificar `front`/`back`,
  embeddings para escolher `left`/`right` por diversidade.

Convenção:
- `views = ["front", "left", "back", "right"]` é a ordem que o Hunyuan
  espera. Fotos extras (5ª e 6ª) ficam após na lista de saída e o
  servidor do Hunyuan ignora (`_MV_VIEW_KEYS = 4` keys).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.view_router")

CARDINAL_VIEWS: tuple[str, ...] = ("front", "left", "back", "right")
VALID_VIEW_LABELS: frozenset[str] = frozenset({*CARDINAL_VIEWS, "extra"})


@dataclass(frozen=True)
class ViewRoutingResult:
    """Resultado de uma rota de vistas.

    `ordered` é a lista final de imagens na ordem que o Hunyuan espera:
    `[front, left, back, right, *extras]`. O servidor do Hunyuan só usa
    as 4 primeiras, mas mantemos as extras na lista para diagnóstico e
    para o stage de textura multi-view.
    """

    ordered: list[Path]
    assignments: dict[str, Path]
    confidences: dict[str, float] = field(default_factory=dict)
    source: str = "positional"  # "positional" | "labeled" | "clip"


class ViewRouter(ABC):
    """Contrato dos routers de vista."""

    @abstractmethod
    async def route(
        self,
        images: list[Path],
        hints: list[str | None] | None = None,
    ) -> ViewRoutingResult: ...


class PositionalViewRouter(ViewRouter):
    """Bypass: devolve as imagens na ordem recebida.

    Replica o comportamento legado (ordem do upload). Útil para testes
    e como fallback quando CLIP não estiver disponível.
    """

    async def route(
        self,
        images: list[Path],
        hints: list[str | None] | None = None,
    ) -> ViewRoutingResult:
        if not images:
            raise ValueError("PositionalViewRouter precisa de pelo menos 1 imagem")

        ordered = list(images[:6])
        assignments = {
            label: ordered[i]
            for i, label in enumerate(CARDINAL_VIEWS)
            if i < len(ordered)
        }
        return ViewRoutingResult(
            ordered=ordered,
            assignments=assignments,
            source="positional",
        )


class LabeledViewRouter(ViewRouter):
    """Usa labels fornecidos pelo cliente (app guiado).

    O cliente envia uma lista paralela `hints` com o rótulo de cada
    imagem ("front", "left", "back", "right" ou "extra"). Este router
    reordena as imagens para a ordem cardinal esperada, deixando os
    "extra" no final.

    Fallbacks:
    - Se hints estiver vazio ou None, delega para o `fallback` router.
    - Se algum cardinal estiver faltando, delega para o `fallback`.
    - Se hints tiver mais de uma imagem por cardinal, a última vence
      (o app trata "refazer" como substituição).
    """

    def __init__(self, fallback: ViewRouter | None = None):
        self.fallback = fallback or PositionalViewRouter()

    async def route(
        self,
        images: list[Path],
        hints: list[str | None] | None = None,
    ) -> ViewRoutingResult:
        if not images:
            raise ValueError("LabeledViewRouter precisa de pelo menos 1 imagem")

        if not hints or all(h is None or h == "" for h in hints):
            _log.info("Sem hints de vista; delegando para fallback")
            return await self.fallback.route(images, hints)

        # Garante mesmo tamanho — preenche com None se faltar.
        if len(hints) < len(images):
            hints = list(hints) + [None] * (len(images) - len(hints))

        cardinais: dict[str, Path] = {}
        extras: list[Path] = []
        for img, hint in zip(images, hints):
            label = (hint or "").strip().lower()
            if label in CARDINAL_VIEWS:
                cardinais[label] = img  # último ganha (refazer)
            else:
                extras.append(img)

        faltando = [v for v in CARDINAL_VIEWS if v not in cardinais]
        if faltando:
            _log.warning(
                "Hints incompletos (faltam: %s); delegando para fallback",
                faltando,
            )
            return await self.fallback.route(images, hints)

        ordered = [cardinais[v] for v in CARDINAL_VIEWS] + extras[:2]
        _log.info(
            "Roteamento por labels: front=%s left=%s back=%s right=%s (+%d extras)",
            cardinais["front"].name,
            cardinais["left"].name,
            cardinais["back"].name,
            cardinais["right"].name,
            len(extras[:2]),
        )
        return ViewRoutingResult(
            ordered=ordered,
            assignments=dict(cardinais),
            confidences={v: 1.0 for v in CARDINAL_VIEWS},
            source="labeled",
        )


class CLIPViewRouter(ViewRouter):
    """Roteia vistas com CLIP zero-shot + embeddings.

    Estratégia:
    1. CLIP zero-shot classifica cada foto contra prompts de `front` e
       `back` (lados com label visível vs. sem).
    2. `front` = foto com maior score no prompt de frente.
    3. `back`  = foto com maior score no prompt de costas, **excluída**
       a já escolhida como front.
    4. Das 2 restantes (ou mais), pega as 2 com **maior distância de
       embedding** entre si — viram `left` e `right` em ordem
       arbitrária (frasco simétrico tolera).
    5. Extras (5ª, 6ª) entram no final preservando ordem original.

    Se o pipeline tiver menos de 4 imagens, o que faltar vira `None`.
    """

    _PROMPTS = {
        "front": (
            "a perfume bottle photographed from the front with the brand "
            "label clearly visible facing the camera"
        ),
        "back": (
            "the back of a perfume bottle, no brand label visible or only "
            "small ingredient text"
        ),
    }

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        fallback: ViewRouter | None = None,
    ):
        if not model_name:
            raise ValueError("model_name não pode ser vazio")
        self.model_name = model_name
        self.fallback = fallback or PositionalViewRouter()
        self._model = None
        self._processor = None

    async def route(
        self,
        images: list[Path],
        hints: list[str | None] | None = None,
    ) -> ViewRoutingResult:
        if not images:
            raise ValueError("CLIPViewRouter precisa de pelo menos 1 imagem")

        # Se hints completos vieram, deixa o LabeledViewRouter decidir.
        if hints and any(h for h in hints if h):
            labeled = LabeledViewRouter(fallback=self)
            return await labeled.route(images, hints)

        if len(images) < 2:
            _log.info("Apenas 1 imagem; sem rota possível, devolvendo positional")
            return await self.fallback.route(images, hints)

        try:
            return await asyncio.to_thread(self._route_sync, images)
        except Exception as exc:
            _log.warning("CLIP routing falhou (%s); usando fallback positional", exc)
            return await self.fallback.route(images, hints)

    # ------------------------------------------------------------------ sync

    def _route_sync(self, images: list[Path]) -> ViewRoutingResult:
        import numpy as np

        self._ensure_loaded()

        # 1. Calcula scores por imagem para cada prompt + features visuais.
        scores_front: list[float] = []
        scores_back: list[float] = []
        embeddings: list[np.ndarray] = []
        for path in images:
            front_p, back_p, feat = self._scores_and_features(path)
            scores_front.append(front_p)
            scores_back.append(back_p)
            embeddings.append(feat)

        # 2. front = argmax(scores_front)
        idx_front = int(np.argmax(scores_front))

        # 3. back = argmax(scores_back) entre os índices restantes
        restantes = [i for i in range(len(images)) if i != idx_front]
        idx_back = max(restantes, key=lambda i: scores_back[i])

        # 4. left/right: das imagens restantes, pega as 2 mais distantes
        sobras = [i for i in restantes if i != idx_back]
        idx_left, idx_right = self._escolher_left_right(sobras, embeddings)

        # 5. extras: restantes em ordem original (até 2)
        usados = {idx_front, idx_left, idx_right, idx_back}
        usados.discard(None)  # type: ignore[arg-type]
        extras_idx = [i for i in range(len(images)) if i not in usados][:2]

        assignments: dict[str, Path] = {"front": images[idx_front]}
        if idx_left is not None:
            assignments["left"] = images[idx_left]
        if idx_right is not None:
            assignments["right"] = images[idx_right]
        assignments["back"] = images[idx_back]

        confidences = {
            "front": float(scores_front[idx_front]),
            "back": float(scores_back[idx_back]),
        }

        # Ordem que o Hunyuan espera: [front, left, back, right, *extras].
        cardinal_order = ["front", "left", "back", "right"]
        cardinal_paths = [assignments[v] for v in cardinal_order if v in assignments]
        extras_paths = [images[i] for i in extras_idx]
        ordered = cardinal_paths + extras_paths

        _log.info(
            "CLIP routing: front=%s (%.2f) left=%s back=%s (%.2f) right=%s",
            images[idx_front].name,
            scores_front[idx_front],
            images[idx_left].name if idx_left is not None else "—",
            images[idx_back].name,
            scores_back[idx_back],
            images[idx_right].name if idx_right is not None else "—",
        )
        return ViewRoutingResult(
            ordered=ordered,
            assignments=assignments,
            confidences=confidences,
            source="clip",
        )

    def _escolher_left_right(
        self, candidatos: list[int], embeddings: list
    ) -> tuple[int | None, int | None]:
        """Das fotos restantes, devolve as 2 com maior distância entre si.

        Frasco simétrico não tem como CLIP distinguir esquerda/direita;
        garantir diversidade entre as 2 já evita mandar duas fotos quase
        iguais. A atribuição left vs right é arbitrária.
        """
        import numpy as np

        if not candidatos:
            return None, None
        if len(candidatos) == 1:
            return candidatos[0], None

        melhor_par: tuple[int, int] | None = None
        melhor_dist = -1.0
        for i, a in enumerate(candidatos):
            for b in candidatos[i + 1 :]:
                emb_a = embeddings[a] / (np.linalg.norm(embeddings[a]) + 1e-8)
                emb_b = embeddings[b] / (np.linalg.norm(embeddings[b]) + 1e-8)
                dist = float(1.0 - np.dot(emb_a, emb_b))
                if dist > melhor_dist:
                    melhor_dist = dist
                    melhor_par = (a, b)

        assert melhor_par is not None
        return melhor_par[0], melhor_par[1]

    def _scores_and_features(self, path: Path):
        import numpy as np
        import torch

        img = _open_rgb_image(path)
        prompts = [self._PROMPTS["front"], self._PROMPTS["back"]]
        inputs = self._processor(
            text=prompts,
            images=img,
            return_tensors="pt",
            padding=True,
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)[0]
            feats = self._model.get_image_features(pixel_values=inputs["pixel_values"])
        probs_list = probs.detach().cpu().tolist()
        feat = feats[0].detach().cpu().numpy().astype(np.float32)
        return probs_list[0], probs_list[1], feat

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        _log.info("Carregando CLIP '%s' para view router...", self.model_name)
        self._model = CLIPModel.from_pretrained(self.model_name)
        self._processor = CLIPProcessor.from_pretrained(self.model_name)


def _open_rgb_image(path: Path):
    """Abre uma imagem respeitando orientação EXIF antes de enviar ao CLIP."""
    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
