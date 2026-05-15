# 04 — Estrutura de pastas

Mapa atual de `c:\TCC\back`. Use este doc como ponto de partida para "onde mora X".

## Árvore raiz

```
back/
├── .env                       # config local (gitignored)
├── .env.example               # template versionado
├── .gitignore
├── README.md                  # quick start (este e o do app concorrem em utilidade)
├── pytest.ini                 # config do pytest
├── requirements.txt           # deps runtime
├── requirements-dev.txt       # deps + ferramentas de teste
├── requirements-classifier.txt # deps opcionais (CLIP / Pillow)
├── requirements-vision.txt    # deps opcionais (rembg / opencv / numpy / Pillow) — pipeline IA
├── app/                       # código-fonte
├── tests/                     # suíte pytest
├── scripts/                   # utilitários offline (Blender, smokes, label)
├── assets/                    # templates 3D versionados
├── docs/                      # esta pasta
├── historico/                 # registro acadêmico (sessões + INDEX.md) — não tracked pelo Git
└── storage/                   # gerado em runtime (gitignored exceto model_viewer.html)
```

## `app/` — código da aplicação

```
app/
├── __init__.py
├── main.py                    # create_app() + production_lifespan + factories
├── config.py                  # Settings (pydantic-settings) + lê .env
├── database.py                # engine + SessionFactory async + create_all()
├── dependencies.py            # get_capture_service (DI do FastAPI)
│
├── core/                      # blocos genéricos compartilhados
│   ├── exceptions.py          # AppError + handler que vira JSON HTTP
│   └── logging.py             # configure_logging + get_logger
│
├── storage/
│   └── local_storage.py       # LocalStorage (uploads/<job>/, models/<job>.glb)
│
└── modules/
    ├── captures/              # módulo principal — todo o fluxo 3D
    │   ├── __init__.py
    │   ├── status.py          # enum CaptureStatus (waiting|processing|completed|error)
    │   ├── models.py          # CaptureJob + CaptureImage (SQLAlchemy 2.0)
    │   ├── schemas.py         # CreateCaptureResponse, CaptureStatusResponse (DTOs camelCase)
    │   ├── repository.py      # CaptureRepository (queries encapsuladas)
    │   ├── service.py         # CaptureService (cria job, persiste, delega ao pipeline)
    │   ├── router.py          # POST /captures, GET /captures/{id}/status
    │   ├── queue.py           # ProcessingQueue (asyncio.Queue + worker)
    │   │
    │   │   # ── Pipeline raiz + IA ──
    │   ├── pipeline.py        # IntegratedPipeline (planejado) — composição de stages
    │   ├── processor.py       # ABC Processor + FakeProcessor + TemplateProcessor + Hunyuan3DProcessor
    │   │
    │   │   # ── Cache de modelos por similaridade CLIP ──
    │   ├── embeddings.py      # ImageEmbedder ABC + ClipImageEmbedder (planejado)
    │   ├── cache.py           # ModelCache ABC + ClipSimilarityCache (planejado)
    │   ├── modelos_universais.py # ModeloUniversal SQLAlchemy (tabela modelos_3d_universais — cache global, planejado)
    │   │
    │   │   # ── Stages do pipeline IA ──
    │   ├── background_remover.py # ABC + DisabledBackgroundRemover + RembgBackgroundRemover
    │   ├── label_extractor.py    # ABC + DisabledLabelExtractor + HomographyLabelExtractor
    │   ├── image_preprocessor.py # ABC + DisabledImagePreprocessor + StandardImagePreprocessor
    │   ├── mesh_cleaner.py       # ABC + DisabledMeshCleaner + BlenderMeshCleaner
    │   ├── mesh_refiner.py       # ABC + DisabledMeshRefiner + BlenderMeshRefiner
    │   ├── label_upscaler.py     # ABC + DisabledLabelUpscaler + LanczosLabelUpscaler
    │   ├── label_projector.py    # ABC + DisabledLabelProjector + BlenderLabelProjector
    │   ├── top_projector.py      # ABC + DisabledTopProjector + BlenderTopProjector (opcional)
    │   │
    │   │   # ── Legado / fallback ──
    │   ├── classifier.py      # ABC Classifier + CLIPClassifier (depreciado — substituído por embeddings.py)
    │   ├── color_detector.py  # ABC ColorDetector + AverageColorDetector (depreciado do fluxo principal)
    │   ├── templates_catalog.py  # template_id → descrição em inglês (usado no fallback do TemplateProcessor)
    │   │
    │   └── blender_scripts/
    │       ├── __init__.py
    │       ├── customize_template.py    # template paramétrico (fallback)
    │       ├── refine_ai_mesh.py        # shader de vidro PBR
    │       ├── cleanup_mesh.py          # ilhas + furos + normais
    │       ├── project_label.py         # decal frontal de label
    │       └── project_top_texture.py   # textura da tampa (opcional)
    │
    ├── sales/                 # API comercial — clientes, produtos, vendas, pagamentos
    │   ├── __init__.py
    │   ├── router.py          # /sales/snapshot, /sales/products, /sales/sales
    │   ├── repository.py      # SalesRepository + ensure_sales_schema (ALTER TABLE bootstrap)
    │   └── schemas.py         # ClienteOut, ProdutoOut, VendaOut, ParcelaOut, ...
    │
    └── health/
        ├── __init__.py
        └── router.py          # GET /health → {"status":"ok"}
```

### Pontos-chave da árvore

- **`main.py` é o único lugar onde tudo se encontra**. As factories `build_pipeline()` (que escolhe entre `FakeProcessor`, `TemplateProcessor` e `IntegratedPipeline` conforme `PIPELINE_MODE`) e os helpers de cada stage (`build_image_preprocessor`, `build_background_remover`, `build_mesh_refiner`, `build_embedder`, `build_model_cache`, etc.) ficam aqui — sem container DI, sem mágica.
- **`modules/captures/` é o módulo principal de domínio 3D**. Reúne o pipeline integrado (`pipeline.py`), o cliente do Hunyuan, os stages auxiliares (preprocess, rembg, refiner, label extractor/upscaler/projector), o cache CLIP e a tabela `modelos_3d_universais` (cache global, cross-tenant — separada da `modelos_3d_produto` que já existe e amarra produto comercial a um molde). O caminho de templates (`TemplateProcessor` + `templates_catalog`) continua presente como **fallback**.
- **`modules/sales/` é o segundo módulo de domínio** (comercial); `health/` é só `/health`.
- **Tudo abaixo de `modules/` segue o padrão Feature-First**: cada módulo carrega seu próprio router, service/repository, schemas. `sales/` é mais enxuto (sem `service.py` separado — a lógica fica no `repository.py` por ser CRUD direto sobre Postgres).
- **`blender_scripts/` é especial**: rodam **dentro** do Blender via `--python`. Não importam nada do `app/` (não conseguiriam — Blender tem o próprio Python isolado). A convenção Blender↔wrapper usa uma única linha estruturada `STATS:...` em stdout para passar contagens (ilhas removidas, faces, índice da face frontal).

## `tests/` — pytest suite

```
tests/
├── __init__.py
├── conftest.py                # fixture session_factory (SQLite em tmp_path)
├── test_main.py               # 13 testes end-to-end via httpx.AsyncClient
│
├── assets/
│   ├── __init__.py
│   └── test_normalized_templates.py   # 25 testes — valida estrutura dos GLBs
│
├── integration/
│   ├── __init__.py
│   └── test_hunyuan_real.py       # exercita /generate de verdade — pulado se contêiner offline
│
└── modules/
    ├── __init__.py
    └── captures/
        ├── __init__.py
        ├── test_classifier.py         # DisabledClassifier + CLIPClassifier mockado
        ├── test_color_detector.py     # AverageColorDetector + edge cases
        ├── test_customize_template.py # script Blender invocado com Blender real
        ├── test_processor.py          # FakeProcessor + TemplateProcessor + Hunyuan3DProcessor (FakeTransport)
        ├── test_queue.py              # ProcessingQueue assíncrona
        ├── test_router.py             # POST/GET via TestClient
        ├── test_service.py            # CaptureService (caminho feliz e erros)
        ├── test_template_processor.py # TemplateProcessor (mocks + integração)
        ├── test_background_remover.py # DisabledBackgroundRemover + RembgBackgroundRemover (importorskip rembg)
        ├── test_label_extractor.py    # HomographyLabelExtractor + _ordenar_cantos
        ├── test_image_preprocessor.py # StandardImagePreprocessor (EXIF, WB, CLAHE, sharpen, resize)
        ├── test_mesh_cleaner.py       # BlenderMeshCleaner mocked + integração Blender
        ├── test_mesh_refiner.py       # BlenderMeshRefiner mocked + integração Blender
        ├── test_label_upscaler.py     # LanczosLabelUpscaler
        └── test_label_projector.py    # BlenderLabelProjector mocked + integração Blender
```

**Total atual: 173 testes** (`pytest --collect-only` no estado em 2026-05-09). Nenhum teste exige Postgres rodando. Vários componentes do pipeline IA pulam quando dependências (`rembg`, `cv2`, Blender 5.1+, contêiner Hunyuan) estão ausentes — convenção `pytest.importorskip` ou guard `if not blender.exists(): pytest.skip(...)`. Detalhes em [14 - Testes](14-testes.md).

## `scripts/` — utilitários offline

```
scripts/
├── smoke.ps1                              # smoke test ponta a ponta via HTTP
├── build_feeling_label.py                 # gera PNG da label do Feelin' Flame com PIL
├── smoke_phase3.py                        # rembg → Hunyuan → refiner (Fase 3)
├── smoke_phase4.py                        # preprocess → rembg → Hunyuan → cleanup → refiner (Fase 4)
├── smoke_phase5.py                        # idem + label_extract → upscale → project (Fase 5)
└── blender/                               # rodam dentro do Blender headless
    ├── inspect_raw_templates.py           # lista materiais/meshes dos GLBs brutos
    ├── normalize_template.py              # padroniza GLBs do Sketchfab
    ├── generate_feeling_template.py       # gera o template procedural V2
    ├── preview_feeling_template.py        # render Cycles (PNG) do template
    └── preview_refinement.py              # render comparativo before/after do refiner
```

Esses scripts **não são chamados pelo backend em runtime**. São ferramentas de bancada para preparar/atualizar templates e fazer smoke tests. Detalhes em [11 - Templates 3D](11-templates-3d.md).

## `assets/` — templates versionados

```
assets/
└── templates/
    ├── ATTRIBUTIONS.md            # créditos dos 6 modelos do Sketchfab
    ├── catalog.json               # mapeia raw → status, license, notes
    ├── raw/                       # gitignored — modelos baixados do Sketchfab
    │   ├── rectangular/
    │   ├── cylindrical/
    │   ├── square/
    │   ├── round/
    │   └── ornamental/
    └── normalized/                # versionado — saída do normalize_template.py
        ├── rectangular_basic.glb
        ├── cylindrical_basic.glb
        ├── square_compact.glb
        ├── round_spherical.glb
        ├── ornamental_modernist.glb
        ├── feeling_rectangular_blue.glb        # procedural (gerado por script próprio)
        ├── feeling_rectangular_blue_label.png  # textura embutida no GLB acima
        ├── feeling_rectangular_blue_preview.png    # render Cycles frontal
        └── feeling_rectangular_blue_preview_3q.png # render Cycles 3/4
```

- **`raw/` é gitignored** — esses arquivos são pesados (10-30MB cada) e têm licenças que requerem atribuição mas não permitem redistribuição em massa. Cada dev que precisar dos raws baixa de novo do Sketchfab seguindo o `ATTRIBUTIONS.md`.
- **`normalized/` é versionado** — esses são os GLBs que o `TemplateProcessor` consome em runtime. Tamanho varia: ~150KB (procedural) até ~26MB (round_spherical).

## `storage/` — gerado em runtime

```
storage/
├── model_viewer.html              # versionado — viewer HTML local
├── uploads/                       # gitignored
│   └── <job_id>/
│       ├── img1.jpg
│       └── ...
├── models/                        # gitignored
│   ├── <job_id>.glb               # GLB entregue (cópia do cache em hit, ou recém-gerado em miss)
│   └── candidates/                # GLBs intermediários para debug (gitignored)
│       └── <job_id>/
├── cache/                         # gitignored — GLBs cacheados, referenciados por modelos_3d_universais.caminho_arquivo_modelo
│   └── <cache_id>.glb
└── smoke/                         # gitignored — outputs dos smokes manuais
    ├── raw.glb, cleaned.glb, refined.glb, with_label.glb
    └── preprocessed/, masked/, label_raw.png, label_upscaled.png
```

A pasta `storage/uploads/`, `storage/models/` e `storage/cache/` são criadas no startup pelo `LocalStorage.ensure_dirs()` ([`app/storage/local_storage.py`](../app/storage/local_storage.py)). O `.gitignore` bloqueia `storage/uploads/`, `storage/models/`, `storage/cache/`, `storage/smoke/`, `storage/*.glb`, `storage/*.gltf` — só o HTML do viewer é versionado.

## `docs/` — esta pasta

Conjunto **01–15** (Markdown) descrevendo o backend, mais quatro docs técnicos do pipeline IA (`09b/c/d/e`) e um doc de segmentação (`10b`). O [README](README.md) desta pasta indica a ordem de leitura.

```
docs/
├── README.md
├── 01-visao-geral.md
├── 02-stack-tecnologico.md
├── 03-inicializacao-do-projeto.md
├── 04-estrutura-de-pastas.md   ← este ficheiro
├── 05-arquitetura.md
├── 06-bootstrap-e-lifespan.md
├── 07-camada-core.md
├── 08-modulo-captures.md
├── 09-pipeline-3d.md                   # TemplateProcessor (fallback)
├── 09b-pipeline-ai-hunyuan.md          # cliente HTTP do contêiner Hunyuan
├── 09c-refinamento-mesh.md             # shader de vidro PBR
├── 09d-preprocessamento-e-cleanup.md   # ImagePreprocessor + MeshCleaner
├── 09e-aplicacao-label.md              # LabelUpscaler + LabelProjector
├── 09f-pipeline-integrado.md           # IntegratedPipeline (composição)
├── 09g-cache-similaridade-clip.md      # ModelCache + modelos_3d_universais (cross-tenant)
├── 10-classificador-e-cor.md           # ImageEmbedder + ColorDetector (legado)
├── 10b-segmentacao-e-label.md          # BackgroundRemover + LabelExtractor
├── 11-templates-3d.md
├── 12-armazenamento-e-banco.md
├── 13-endpoints-http.md
├── 14-testes.md
└── 15-glossario.md
```

## Convenções de import e organização

- **Imports absolutos a partir de `app/`** dentro do código (`from ...core.logging import get_logger`). Os `..` relativos só aparecem quando o ganho de legibilidade é claro.
- **Cada módulo expõe seu router via `from .router import router`**, e `main.py` faz `app.include_router(captures_router)`.
- **Arquivos `__init__.py` ficam vazios** — o agrupamento é por nome, não por re-export. Procure pelo arquivo final, não por barril.
- **Lazy imports para libs pesadas**: `transformers` em `classifier.py` e `Pillow` em `color_detector.py` são importados dentro dos métodos. Permite que o módulo seja importado mesmo sem essas deps instaladas (caso `CLASSIFIER_TYPE=disabled`).

## Próximas leituras

- Como as camadas conversam: [05 - Arquitetura](05-arquitetura.md).
- Detalhe do módulo principal: [08 - Módulo `captures`](08-modulo-captures.md).
