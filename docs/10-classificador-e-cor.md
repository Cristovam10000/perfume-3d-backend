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
| `CLIPClassifier` → `ClipImageEmbedder` | **Repurposado e removido** | CLIP deixou de escolher entre os 6 templates e passou a produzir embedding 512-d usado pelo `ModelCache`. O `classifier.py` foi apagado em 2026-08. |
| `AverageColorDetector` | **Deprecado do fluxo principal** | Hunyuan infere cor das fotos automaticamente. Mantido como componente histórico; pode ser ativado para persistir cor como metadado. |

A ABC raiz `Classifier` **foi removida em 2026-08** junto com o `TemplateProcessor` — nada mais a chamava. O `IntegratedPipeline` usa `ImageEmbedder` (em `embeddings.py`). Hoje o mesmo checkpoint CLIP serve a tres usos: embeddings do cache, `CLIPViewRouter` e `ClipTransparencyClassifier`.

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

**Não.** Foi removido em 2026-08 junto com o `TemplateProcessor` e o `classifier.py`. O mapa `template_id → descrição em inglês` só servia ao CLIP zero-shot para escolher entre os 6 templates, e nenhum código restante faz essa escolha.

Os GLBs em `assets/templates/normalized/` continuam versionados, mas agora com um único consumidor: `eval/synthetic_dataset.py`. Ver [11 - Templates 3D](11-templates-3d.md).

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

1. **`MeshRefiner`**: o refiner aceita `--liquid-color` e aplica no material `water`/`Liquid` quando ele existe no GLB. O detector continua sendo o jeito de obter essa cor a partir das fotos — falta apenas liga-lo no `IntegratedPipeline`.
2. **Metadado em `modelos_3d_universais.liquid_color`**: se você quiser registrar a cor inferida das fotos junto com o GLB cacheado (útil para o módulo `sales` exibir "perfume azul" no card), o `IntegratedPipeline` pode chamar o detector antes do `cache.store(...)`. Está fora do MVP do cache, mas é a forma de manter a feature viva.

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
- **Color detector falhou** (se estiver ativo): loga warning; o pipeline segue sem `liquid_color`. Hunyuan ignora; o refiner mantem o material original.

## Leituras relacionadas

- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md) (consumidor do embedder)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [02 — Stack tecnológico](02-stack-tecnologico.md) (deps do CLIP)
- [16 — Auditoria do papel do Blender](16-auditoria-blender.md) (por que `classifier.py` e `templates_catalog.py` sairam)
- Código: [`app/modules/captures/embeddings.py`](../app/modules/captures/embeddings.py), [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py)
