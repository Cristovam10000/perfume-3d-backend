# 09f — Pipeline integrado (`IntegratedPipeline`)

> **O que você vai aprender neste doc**
> - Como o `IntegratedPipeline` **compõe** os stages num único `Processor` — o coração do backend.
> - O curto-circuito do cache: quando o fluxo para no stage (3) com um HIT.
> - A regra de **degradação graciosa**: um GLB quase sempre é entregue, mesmo com falhas parciais.
> - Como configurar cada stage pelo `.env` e como a factory `build_pipeline()` monta tudo.
>
> **Pré-requisitos:** [05 - Arquitetura](05-arquitetura.md) e [08 - Módulo captures](08-modulo-captures.md).
> Cada stage tem doc próprio: [09b](09b-pipeline-ai-hunyuan.md), [09c](09c-refinamento-mesh.md), [09d](09d-preprocessamento-e-cleanup.md), [09e](09e-aplicacao-label.md), [09g](09g-cache-similaridade-clip.md).

O `IntegratedPipeline` é o `Processor` **default** do backend (`PIPELINE_MODE=integrated`): ele é composto e plugado no `CaptureService` pela factory `build_pipeline()` em `app/main.py`. Este documento descreve como o pipeline compõe os stages, como decide entre cache hit e cache miss (cache **global cross-tenant** via `modelos_3d_universais`), como degrada em falhas parciais e como se configura via `.env`. A separação entre cache global e amarração por tenant (`modelos_3d_produto`) está em [09g](09g-cache-similaridade-clip.md).

## Visão geral

O `IntegratedPipeline` é o `Processor` "default" do backend. Implementa `process(input: ProcessingInput) → ProcessingResult`. Internamente, executa até 8 stages em sequência. O fluxo curta-circuita no stage (3) se o `ModelCache` retorna hit.

```
ProcessingInput (job_id, image_paths, output_path)
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ (1) ImagePreprocessor                                              │
│     image_paths → preprocessed_paths                               │
│     [EXIF + WB + CLAHE + sharpen condicional + resize ≤2048]       │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ (2) BackgroundRemover                                              │
│     preprocessed_paths → masked_paths (PNG RGBA com alpha)         │
│     [rembg isnet-general-use]                                      │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ (3) ModelCache.lookup(preprocessed_paths)                          │
│     ImageEmbedder.embed(...) → embedding 512-d                     │
│     cosine vs modelos_3d_universais.embedding                              │
└───────────────────────────────────────────────────────────────────┘
    │
    ├── HIT (sim ≥ threshold)
    │       │
    │       ▼
    │   copia cache/<id>.glb → output_path
    │   atualiza hit_count + last_hit_at
    │   return ProcessingResult(origem="cache", message=...)
    │
    └── MISS
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (4) Hunyuan3DProcessor                                     │
        │     masked_paths → raw.glb                                 │
        │     [POST /generate no Docker, ~3-8min na GPU]             │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (5) MeshCleaner                                            │
        │     raw.glb → cleaned.glb  (no-op default)                 │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (6) MeshRefiner                                            │
        │     cleaned.glb → refined.glb  (shader de vidro PBR)       │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (7) LabelExtractor + Upscaler + Projector                  │
        │     foto + máscara → label.png → label_upscaled.png        │
        │     refined.glb + label_upscaled.png → with_label.glb      │
        │     degrade: se não achou label, copia refined → output    │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (8) ModelCache.store(embedding, with_label.glb, meta,      │
        │                       product_id?)                         │
        │     persiste em storage/cache/<uuid>.glb                   │
        │     INSERT em modelos_3d_universais                        │
        │     se product_id veio: UPSERT em modelos_3d_produto       │
        │       (ON CONFLICT (produto_id) DO UPDATE                  │
        │        SET modelo_universal_id = EXCLUDED.modelo...)       │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        copia with_label.glb → output_path
        return ProcessingResult(origem="generated", message=...)
```

## Responsabilidades

O `IntegratedPipeline` é o **único** componente que conhece a sequência. Cada stage individual continua isolado e testável em separado.

```python
# Assinatura real (pipeline.py), simplificada
class IntegratedPipeline(Processor):
    def __init__(
        self,
        preprocessor: ImagePreprocessor,
        background_remover: BackgroundRemover,
        embedder: ImageEmbedder,
        cache: ModelCache,
        hunyuan: Hunyuan3DProcessor,
        mesh_cleaner: MeshCleaner,
        mesh_refiner: MeshRefiner,
        label_extractor: LabelExtractor,
        label_upscaler: LabelUpscaler,
        label_projector: LabelProjector,
        storage: LocalStorage,
        *,
        view_router: ViewRouter | None = None,        # rotula vistas p/ o Hunyuan
        fallback_processor: Processor | None = None,  # TemplateProcessor
        front_axis: str = "front_y_neg",
        min_island_ratio: float = 0.0,
        label_min_confidence: float = 0.3,
        label_target_size: int = 2048,
    ): ...

    async def process(self, input: ProcessingInput) -> ProcessingResult: ...
```

`ProcessingInput` tem um campo opcional `product_id: int | None = None`. O service repassa o valor recebido do `POST /captures` (`productId` no form-data) para o pipeline, que o entrega ao `ModelCache.store(...)` no stage (8). O pipeline em si não conhece a tabela `modelos_3d_produto` — quem faz o UPSERT é o `ClipSimilarityCache`.

Cada dependência é uma ABC, então o pipeline pode ser instanciado com `Disabled*` em qualquer stage para teste — útil em testes unitários (`tests/modules/captures/test_pipeline.py`).

## Falhas e degrade

Comportamento por stage quando algo falha. Em todos os casos o pipeline **loga** o problema e tenta seguir; só aborta se não houver como produzir nenhum GLB.

| Stage | Comportamento em falha |
|---|---|
| (1) Preprocess | Cai para `DisabledImagePreprocessor` (cópia). Loga warning. Hunyuan recebe foto crua. |
| (2) Background remove | Mesma coisa: cópia byte-a-byte. Hunyuan recebe foto preprocessada sem máscara — qualidade cai mas job conclui. |
| (3) Cache lookup | Trata como miss. Loga warning. |
| (4) Hunyuan | **Crítico.** Se `fallback_processor` configurado (`PIPELINE_FALLBACK_TO_TEMPLATE=true`), tenta o `TemplateProcessor`. Caso contrário, levanta `ProcessingError` e o service marca `error`. |
| (5) Mesh cleaner | Cópia. Refiner recebe `raw.glb`. |
| (6) Mesh refiner | Cópia. Label projector recebe `cleaned.glb` (ou `raw.glb`). |
| (7) Label extract | Tenta fallback por recorte; senão, degrade total — devolve `refined.glb` direto, sem label. |
| (8) Cache store | Loga warning mas **não** falha o job. O GLB já está disponível no `output_path`. |

A propriedade chave: **um GLB sempre é entregue, exceto se o Hunyuan falhar e não houver fallback de template**.

## Configuração (`.env`)

Variáveis novas e renomeadas em relação ao layout anterior:

```bash
# ---- Modo do pipeline ----
# fake       = FakeProcessor (cubo sintetico, ~3s, sem deps externas)
# template   = TemplateProcessor (Blender headless, ~5-15s, sem cache)
# integrated = IntegratedPipeline (cache CLIP + Hunyuan + pos-proc) - default
PIPELINE_MODE=integrated

# ---- Hunyuan ----
HUNYUAN_URL=http://localhost:7860
HUNYUAN_TIMEOUT_SECONDS=1200
HUNYUAN_OCTREE_RESOLUTION=384
HUNYUAN_NUM_INFERENCE_STEPS=75
HUNYUAN_GUIDANCE_SCALE=7.5
HUNYUAN_MC_ALGO=mc
HUNYUAN_TEXTURE_RESOLUTION=2048

# ---- Cache de modelos ----
CACHE_ENABLED=true
CACHE_SIMILARITY_THRESHOLD=0.92
CACHE_EMBEDDING_MODEL=openai/clip-vit-base-patch32

# ---- Stages auxiliares ----
IMAGE_PREPROCESSOR_TYPE=standard      # disabled | standard
BACKGROUND_REMOVER_TYPE=rembg         # disabled | rembg
MESH_CLEANER_TYPE=disabled            # disabled | blender (default disabled — bypass)
MESH_REFINER_TYPE=blender             # disabled | blender
LABEL_EXTRACTOR_TYPE=homography       # disabled | homography
LABEL_UPSCALER_TYPE=lanczos           # disabled | lanczos
LABEL_PROJECTOR_TYPE=blender          # disabled | blender
LABEL_FRONT_AXIS=front_y_neg
LABEL_MIN_CONFIDENCE=0.3
LABEL_TARGET_SIZE=2048

# ---- Fallback ----
PIPELINE_FALLBACK_TO_TEMPLATE=false   # se true, usa TemplateProcessor quando Hunyuan falha
DEFAULT_TEMPLATE_ID=rectangular_basic
TEMPLATES_DIR=./assets/templates/normalized
BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe
```

Compat: o valor antigo `PROCESSOR_TYPE` é lido como `PIPELINE_MODE` se estiver presente (com *deprecation warning*) — ver `_apply_legacy_aliases` em `config.py`. Valores legados `fake`/`template`/`integrated` são mapeados; valores desconhecidos (ex.: `template_fitting`, que apareceu por engano em `.env` antigos) caem no default `integrated` sem quebrar o startup.

## Factory (`app/main.py`)

```python
def build_pipeline(
    config: Settings = settings,
    storage: LocalStorage | None = None,
) -> Processor:
    storage = storage or LocalStorage()
    if config.pipeline_mode == "fake":
        return FakeProcessor()
    if config.pipeline_mode == "template":
        return build_template_processor(config)
    # integrated (default)
    return IntegratedPipeline(
        preprocessor=build_image_preprocessor(config),
        background_remover=build_background_remover(config),
        embedder=build_embedder(config),
        cache=build_model_cache(config),
        hunyuan=build_hunyuan(config),
        mesh_cleaner=build_mesh_cleaner(config),
        mesh_refiner=build_mesh_refiner(config),
        label_extractor=build_label_extractor(config),
        label_upscaler=build_label_upscaler(config),
        label_projector=build_label_projector(config),
        storage=storage,
        view_router=build_view_router(config),
        fallback_processor=(
            build_template_processor(config) if config.pipeline_fallback_to_template else None
        ),
        front_axis=config.label_front_axis,
        min_island_ratio=config.mesh_min_island_ratio,
        label_min_confidence=config.label_min_confidence,
        label_target_size=config.label_target_size,
    )
```

## Tempo total esperado

| Cenário | Tempo |
|---|---|
| Cache HIT | ~3–8 s (preprocess + rembg + lookup + cópia) |
| Cache MISS, Hunyuan rápido | ~4 min (preprocess + rembg + Hunyuan + cleaner + refiner + label + store) |
| Cache MISS, Hunyuan lento | ~10 min |
| Fallback para `TemplateProcessor` | ~30 s (preprocess + rembg + template + label) |

## Diferença para o smoke histórico

O `scripts/smoke_phase5.py` já implementa **uma versão imperativa** dessa mesma sequência. A diferença é estrutural:

- `smoke_phase5.py` é um script: argumentos CLI, prints, instancia cada stage com defaults. **Não toca em banco** nem na fila do `CaptureService`.
- `IntegratedPipeline` é uma classe: injeção de dependências, recebe `ProcessingInput`, devolve `ProcessingResult`. **Roda dentro do worker** do `CaptureService` e persiste no cache.

O smoke continuará útil para depurar etapas isoladas; o pipeline é o caminho de produção.

## Testes

[`tests/modules/captures/test_pipeline.py`](../tests/modules/captures/test_pipeline.py) (6 testes) cobre, com mocks de cada stage:

  - Cenário cache HIT: confirma que stages (4)–(8) **não** são chamados.
  - Cenário cache MISS: confirma que todos os stages são chamados na ordem.
  - Degrade do refiner: confirma que o job conclui usando `cleaned.glb`.
  - Falha do Hunyuan com fallback ativo: confirma que o `TemplateProcessor` é chamado.
  - Falha do Hunyuan sem fallback: confirma `ProcessingError` propagada.

## Leituras relacionadas

- [09 — Pipeline 3D (TemplateProcessor — fallback)](09-pipeline-3d.md)
- [09b — Pipeline IA Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09c — Refinamento de Malha](09c-refinamento-mesh.md)
- [09d — Pré-processamento e Cleanup](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de Label Real](09e-aplicacao-label.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
- [05 — Arquitetura](05-arquitetura.md)
- [08 — Módulo `captures`](08-modulo-captures.md)
