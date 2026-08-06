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
        │ (5) TransparencyClassifier                                 │
        │     preprocessed_paths → body_mode (glass | keep | auto)   │
        │     [CLIP zero-shot: frasco transparente ou opaco?]        │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (6) MeshRefiner                                            │
        │     raw.glb → refined.glb                                  │
        │     [segmenta corpo/tampa e aplica vidro PBR só no corpo   │
        │      se body_mode=glass; intacto se keep]                  │
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
        │ (7.4) BackProjector  → with_back.glb  (só se opaco)        │
        │ (7.5) TopProjector   → with_top.glb   (só se foto aprovada)│
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (7.9) GlbOptimizer → optimized.glb                         │
        │      compressão Draco (~5,5x); último da cadeia porque o   │
        │      artefato final varia com os opcionais que rodaram     │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        copia optimized.glb → output_path
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (7.95) PreviewRenderer → storage/models/<job>.png          │
        │      renderiza o GLB já entregue (não um intermediário)    │
        │      opcional: falha → preview_path=None                   │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        ┌───────────────────────────────────────────────────────────┐
        │ (8) ModelCache.store(embedding, optimized.glb, meta,       │
        │                       product_id?)                         │
        │     persiste em storage/cache/<uuid>.glb                   │
        │     INSERT em modelos_3d_universais                        │
        │     se product_id veio: UPSERT em modelos_3d_produto       │
        │       (só para gravar modelo_universal_id — o vínculo em   │
        │        si é do service, ver abaixo)                        │
        └───────────────────────────────────────────────────────────┘
            │
            ▼
        return ProcessingResult(origem="generated", message=...,
                                preview_path=...)
            │
            ▼
        CaptureService._mark_completed()
            UPSERT em modelos_3d_produto (caminho do GLB + preview)
            UPDATE produtos.possui_modelo_3d = true
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
        mesh_refiner: MeshRefiner,
        label_extractor: LabelExtractor,
        label_upscaler: LabelUpscaler,
        label_projector: LabelProjector,
        storage: LocalStorage,
        *,
        view_router: ViewRouter | None = None,        # rotula vistas p/ o Hunyuan
        transparency_classifier: TransparencyClassifier | None = None,  # vidro ou opaco
        front_axis: str = "front_y_neg",
        label_min_confidence: float = 0.3,
        label_target_size: int = 2048,
    ): ...

    async def process(self, input: ProcessingInput) -> ProcessingResult: ...
```

`ProcessingInput` tem um campo opcional `product_id: int | None = None`. O service repassa o valor recebido do `POST /captures` (`productId` no form-data) para o pipeline, que o entrega ao `ModelCache.store(...)` no stage (8).

O pipeline **não** amarra o produto ao modelo. Quem escreve `modelos_3d_produto` é o `CaptureService._mark_completed()`, via `CaptureRepository.vincular_produto()`. Esse vínculo já morou dentro do `ModelCache.store()` e ficava refém do `CACHE_ENABLED`: com o cache desligado, o job concluía, o GLB ia para o disco e o produto continuava sem modelo. Ver [17 - Defeito 4](17-fidelidade-do-modelo.md#defeito-4--o-modelo-ficava-pronto-e-o-produto-não-sabia). O cache ainda cuida do `modelo_universal_id`, coluna que é dele.

Cada dependência é uma ABC, então o pipeline pode ser instanciado com `Disabled*` em qualquer stage para teste — útil em testes unitários (`tests/modules/captures/test_pipeline.py`).

## Falhas e degrade

Comportamento por stage quando algo falha. Em todos os casos o pipeline **loga** o problema e tenta seguir; só aborta se não houver como produzir nenhum GLB.

| Stage | Comportamento em falha |
|---|---|
| (1) Preprocess | Cai para `DisabledImagePreprocessor` (cópia). Loga warning. Hunyuan recebe foto crua. |
| (2) Background remove | Mesma coisa: cópia byte-a-byte. Hunyuan recebe foto preprocessada sem máscara — qualidade cai mas job conclui. |
| (3) Cache lookup | Trata como miss. Loga warning. |
| (4) Hunyuan | **Crítico e terminal.** Levanta `ProcessingError` e o service marca o job como `error`. Não há fallback — mascarar a falha poluía a medição do pipeline de IA. |
| (5) Transparência | Se o app enviou `material`, nem chama o CLIP. Sem `material` e com falha no CLIP, trata como desconhecido — refiner roda em `body_mode=auto`. Ver [17](17-fidelidade-do-modelo.md#defeito-1--frasco-opaco-classificado-como-vidro). |
| (6) Mesh refiner | Cópia. Label projector recebe `raw.glb`. Se o refiner rodar mas não achar o ombro, aplica vidro no material único (comportamento anterior à segmentação). |
| (7) Label extract | Degrade total — devolve `refined.glb` direto, sem label. **Atenção:** hoje este é o caminho de 100% dos jobs; ver [16 - Auditoria](16-auditoria-blender.md). |
| (7.4) Back projector | No-op quando o frasco não é opaco (`body_mode != keep`) — em vidro, colar foto opaca no verso mataria a transmissão. Se o Blender falhar, mantém o GLB anterior. Ver [17](17-fidelidade-do-modelo.md#defeito-3--o-verso-do-frasco-era-inventado). |
| (7.5) Top projector | No-op quando o app não rotula nenhuma foto como `top` **ou** quando a foto reprova na checagem de elongação (o motivo vai para a `message` do job). Se o Blender falhar, mantém o GLB anterior e loga warning. |
| (7.9) GLB optimizer | Entrega o GLB sem comprimir e loga warning. Um arquivo grande é melhor que nenhum arquivo. |
| (7.95) Preview | `ProcessingResult.preview_path` vem `None` e o card do produto usa o visual genérico — que era o comportamento antes desta etapa existir. |
| (8) Cache store | Loga warning mas **não** falha o job. O GLB já está disponível no `output_path`. |

A propriedade chave: **um GLB sempre é entregue, exceto se o Hunyuan falhar**.

### Ordem dos dois últimos estágios

A compressão roda **depois** de todos os projetores porque qual deles produziu o artefato final varia com os opcionais que dispararam — comprimir no meio da cadeia obrigaria os seguintes a descomprimir e recomprimir. O preview roda **depois da cópia** para `output_path`, renderizando o GLB que o app vai de fato baixar, não um intermediário do workspace.

> **Degradação silenciosa.** Os stages opcionais logam em INFO/WARNING e seguem. Isso permitiu que o extrator de rótulo ficasse quebrado por meses sem ninguém notar — nenhum job jamais produziu `with_label.glb`. Ao investigar qualidade de saída, verifique nos logs quais stages **efetivamente agiram**, não apenas se o job concluiu.

## Configuração (`.env`)

Variáveis novas e renomeadas em relação ao layout anterior:

```bash
# ---- Modo do pipeline ----
# fake       = FakeProcessor (cubo sintetico, ~3s, sem deps externas)
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
MESH_REFINER_TYPE=blender             # disabled | blender (segmenta corpo/tampa antes do vidro)
TRANSPARENCY_CLASSIFIER_TYPE=clip     # disabled | clip (decide vidro vs opaco p/ o refiner)
TRANSPARENCY_THRESHOLD=0.30           # prob. media minima p/ classificar transparente
LABEL_EXTRACTOR_TYPE=homography       # disabled | homography
LABEL_UPSCALER_TYPE=lanczos           # disabled | lanczos
LABEL_PROJECTOR_TYPE=blender          # disabled | blender
LABEL_FRONT_AXIS=front_y_neg
LABEL_MIN_CONFIDENCE=0.3
LABEL_TARGET_SIZE=2048
TOP_PROJECTOR_TYPE=blender            # disabled | blender — cola a foto do topo na tampa
TOP_COSINE_THRESHOLD=0.45             # cosseno minimo p/ a face contar como topo

# ---- Blender ----
BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe
```

> Removidas em 2026-08 junto com o caminho de templates: `PIPELINE_FALLBACK_TO_TEMPLATE`, `DEFAULT_TEMPLATE_ID`, `TEMPLATES_DIR`. Também removidas `MESH_CLEANER_TYPE` e `MESH_MIN_ISLAND_RATIO` — ver [16 - Auditoria](16-auditoria-blender.md).

Compat: o valor antigo `PROCESSOR_TYPE` é lido como `PIPELINE_MODE` se estiver presente (com *deprecation warning*) — ver `_apply_legacy_aliases` em `config.py`. Apenas `fake`/`integrated` são mapeados; valores desconhecidos — incluindo `template`, agora inválido — caem no default `integrated` sem quebrar o startup.

## Factory (`app/main.py`)

```python
def build_pipeline(
    config: Settings = settings,
    storage: LocalStorage | None = None,
) -> Processor:
    storage = storage or LocalStorage()
    if config.pipeline_mode == "fake":
        return FakeProcessor()
    # integrated (default)
    return IntegratedPipeline(
        preprocessor=build_image_preprocessor(config),
        background_remover=build_background_remover(config),
        embedder=build_embedder(config),
        cache=build_model_cache(config),
        hunyuan=build_hunyuan(config),
        mesh_refiner=build_mesh_refiner(config),
        label_extractor=build_label_extractor(config),
        label_upscaler=build_label_upscaler(config),
        label_projector=build_label_projector(config),
        storage=storage,
        view_router=build_view_router(config),
        transparency_classifier=build_transparency_classifier(config),
        top_projector=build_top_projector(config),
        front_axis=config.label_front_axis,
        top_cosine_threshold=config.top_cosine_threshold,
        label_min_confidence=config.label_min_confidence,
        label_target_size=config.label_target_size,
    )
```

## Tempo total esperado

| Cenário | Tempo |
|---|---|
| Cache HIT | ~3–8 s (preprocess + rembg + lookup + cópia) |
| Cache MISS, Hunyuan rápido | ~4 min (preprocess + rembg + Hunyuan + refiner + label + store) |
| Cache MISS, Hunyuan lento | ~10 min |
| Falha do Hunyuan | job marcado como `error` (sem fallback) |

## Diferença para o smoke histórico

O `scripts/smoke_phase5.py` já implementa **uma versão imperativa** dessa mesma sequência. A diferença é estrutural:

- `smoke_phase5.py` é um script: argumentos CLI, prints, instancia cada stage com defaults. **Não toca em banco** nem na fila do `CaptureService`.
- `IntegratedPipeline` é uma classe: injeção de dependências, recebe `ProcessingInput`, devolve `ProcessingResult`. **Roda dentro do worker** do `CaptureService` e persiste no cache.

O smoke continuará útil para depurar etapas isoladas; o pipeline é o caminho de produção.

## Testes

[`tests/modules/captures/test_pipeline.py`](../tests/modules/captures/test_pipeline.py) (11 casos coletados) cobre, com mocks de cada stage:

  - Cenário cache HIT: confirma que stages (4)–(8) **não** são chamados.
  - Cache HIT com `product_id`: confirma o vínculo do modelo ao produto.
  - Cenário cache MISS: confirma que todos os stages são chamados na ordem.
  - Ausência de label: confirma a degradação graciosa sem interromper o pipeline.
  - Transparência: confirma os modos transparente, opaco e automático do refiner.
  - Falha do classificador de transparência: confirma a degradação para modo automático.
  - Falha do Hunyuan: confirma `ProcessingError` propagada e job encerrado.

## Leituras relacionadas

- [09 — Pipeline 3D (abstração `Processor`)](09-pipeline-3d.md)
- [09b — Pipeline IA Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09c — Refinamento de Malha](09c-refinamento-mesh.md)
- [09d — Pré-processamento de imagem](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de Label Real](09e-aplicacao-label.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
- [09h — Segmentação corpo/tampa](09h-segmentacao-corpo-tampa.md)
- [16 — Auditoria do papel do Blender](16-auditoria-blender.md)
- [05 — Arquitetura](05-arquitetura.md)
- [08 — Módulo `captures`](08-modulo-captures.md)
