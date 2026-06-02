# 10 — Embedder CLIP e detector de cor

> **O que você vai aprender neste doc**
> - Como o CLIP foi **repurposado**: de classificador de template para *embedder* do cache (mesmo modelo, uso novo).
> - Por que o `ColorDetector` saiu do fluxo principal (o Hunyuan já infere a cor).
> - Quando ainda faz sentido ligar cada um (modo `template`, metadado de cor).
>
> **Pré-requisitos:** [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md) (onde o embedder é consumido).

Dois componentes que vinham juntos no MVP de templates: **classificação de forma** via CLIP zero-shot e **detecção de cor do líquido**. Com o pipeline integrado (Hunyuan + cache), ambos mudaram de papel.

| Componente | Estado | Função |
|---|---|---|
| `CLIPClassifier` → `ClipImageEmbedder` | **Repurposado** | CLIP deixa de escolher entre os 6 templates e passa a produzir embedding 512-d usado pelo `ModelCache` (similaridade visual). |
| `AverageColorDetector` | **Deprecado do fluxo principal** | Hunyuan infere cor das fotos automaticamente. Mantido como componente histórico; pode ser ativado para persistir cor como metadado. |

A ABC raiz `Classifier` continua existindo no código (`app/modules/captures/classifier.py`), mas o `CaptureService` não a chama mais. O `IntegratedPipeline` usa `ImageEmbedder` (em `embeddings.py`) no lugar.

## Embedder CLIP — `ImageEmbedder`

Documentado em detalhe em [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md) §"Embeddings".

Resumo:

- `ImageEmbedder` é a ABC; produz `ImageEmbedding(vector, dim, source_paths)`.
- `DisabledEmbedder` retorna zeros (combinado com `DisabledModelCache` desliga o cache inteiro).
- `ClipImageEmbedder` (quando `CACHE_EMBEDDER_TYPE=clip`):
  - Reutiliza `CLIPModel` + `CLIPProcessor` do HuggingFace (`CACHE_EMBEDDING_MODEL`, default `openai/clip-vit-base-patch32`). Mesmo modelo que o classificador legado usava.
  - Para cada imagem: PIL + EXIF + processor.image_processor + vision_model → 512-d.
  - Faz **mean-pool** dos vetores das N imagens do job → 1 vetor de 512.
  - **L2-normalize**: cosine vira produto interno trivial.
  - Inferência roda em `asyncio.to_thread`.

Requer `pip install -r requirements-classifier.txt` (torch, transformers, pillow). Mesma dependência do classificador legado — não acrescenta peso.

## Por que abandonar o `CLIPClassifier`

O `CLIPClassifier` zero-shot recebia descrições em inglês dos 6 templates e devolvia o mais provável:

```python
TEMPLATE_DESCRIPTIONS = {
    "feeling_rectangular_blue": "a tall slim rectangular dark blue glass perfume bottle ...",
    "rectangular_basic": "a tall rectangular glass perfume bottle with a square cap",
    ...
}
```

Faz sentido quando o pipeline depende de templates pré-existentes. O `IntegratedPipeline` **não** depende — o Hunyuan gera geometria do zero. Forçar a classificação por descrição:

1. Adiciona um ponto de falha (CLIP pode atribuir um template ruim).
2. Não é usado para nada no fluxo integrado (Hunyuan ignora `template_id`).
3. Reusa CPU/GPU sem retorno.

A solução é repurposar: **mesmo modelo, mesma carga, uso diferente**. Em vez de comparar a foto com texto, comparamos foto com foto (cache lookup). O CLIP foi treinado exatamente para isso (contrastive image-text-image alinhamento).

## `templates_catalog` ainda existe?

Sim, em `app/modules/captures/templates_catalog.py`. Continua sendo usado por:

- `TemplateProcessor` (fallback do pipeline integrado): se o backend cair no fallback, precisa escolher um template. Por enquanto, escolhe `default_template_id` direto (sem CLIP). Numa evolução, o `templates_catalog` poderia voltar a alimentar o CLIP só para o caminho de fallback.
- Documentação histórica do MVP de templates.

Se você apagar `templates_catalog.py`, o fallback ainda funciona usando `default_template_id`. A escolha é manter como referência.

## Detector de cor — `ColorDetector`

`ColorDetector` ABC continua em `app/modules/captures/color_detector.py`.

### `DisabledColorDetector`

Bypass: sempre `None`. **É o default no pipeline integrado.**

### `AverageColorDetector` (quando `COLOR_DETECTOR_TYPE=average`)

Lógica:
- Abre cada imagem com Pillow, corrige EXIF com `ImageOps.exif_transpose`.
- Recorta o **centro** da imagem (razão configurável, default 40% da largura/altura).
- Calcula RGB médio; opcionalmente filtra pixels muito acinzentados (`_chromatic_pixels`) para aproximar a cor do líquido e não o fundo.
- Retorna string `#RRGGBB` em maiúsculas.

### Quando ativar

No pipeline integrado, a cor do líquido vem do Hunyuan (que infere do conjunto de fotos). O `AverageColorDetector` não é necessário.

Cenários onde ainda faz sentido:

1. **`PIPELINE_MODE=template`** (caminho legado de templates): aí a cor é aplicada no shader `water` do template via `--liquid-color` no Blender. O detector continua sendo o jeito de obter essa cor.
2. **Metadado em `modelos_3d_universais.liquid_color`**: se você quiser registrar a cor inferida das fotos junto com o GLB cacheado (útil para o módulo `sales` exibir "perfume azul" no card), o `IntegratedPipeline` pode chamar o detector antes do `cache.store(...)`. Está fora do MVP do cache, mas é a forma de manter a feature viva.
3. **Substituto barato quando Hunyuan offline + fallback de template ativo**.

Não utiliza **OpenCV**; seria possível trocar a implementação no futuro mantendo a mesma ABC.

## Configuração (`.env`)

```bash
# Embedder do cache
CACHE_EMBEDDER_TYPE=clip                       # disabled | clip
CACHE_EMBEDDING_MODEL=openai/clip-vit-base-patch32

# Detector de cor (fluxo legado / metadado opcional)
COLOR_DETECTOR_TYPE=disabled                   # disabled | average
```

## Tolerância a falhas

- **Embedder falhou** durante o stage (3) do pipeline integrado: `ModelCache.lookup` trata como miss; loga warning. Job segue para Hunyuan.
- **Cache desligado** (`CACHE_ENABLED=false`): todos os jobs viram miss. Equivalente a não ter cache.
- **Color detector falhou** (se estiver ativo): loga warning; o pipeline segue sem `liquid_color`. Hunyuan ignora; `TemplateProcessor` usa cor padrão do template.

## Leituras relacionadas

- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md) (consumidor do embedder)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [02 — Stack tecnológico](02-stack-tecnologico.md) (deps do CLIP)
- Código: [`app/modules/captures/embeddings.py`](../app/modules/captures/embeddings.py), [`app/modules/captures/classifier.py`](../app/modules/captures/classifier.py) (legado), [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py), [`app/modules/captures/templates_catalog.py`](../app/modules/captures/templates_catalog.py)
