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
├── app/                       # código-fonte
├── tests/                     # suíte pytest
├── scripts/                   # utilitários offline (Blender, smoke, label)
├── assets/                    # templates 3D versionados
├── docs/                      # esta pasta
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
    │   ├── service.py         # CaptureService (orquestração das use cases)
    │   ├── router.py          # POST /captures, GET /captures/{id}/status
    │   ├── queue.py           # ProcessingQueue (asyncio.Queue + worker)
    │   ├── processor.py       # ABC Processor + FakeProcessor + TemplateProcessor
    │   ├── classifier.py      # ABC Classifier + DisabledClassifier + CLIPClassifier
    │   ├── color_detector.py  # ABC ColorDetector + Disabled + AverageColorDetector
    │   ├── templates_catalog.py  # template_id → descrição em inglês para CLIP
    │   └── blender_scripts/
    │       ├── __init__.py
    │       └── customize_template.py   # roda DENTRO do Blender (importa bpy)
    │
    └── health/
        ├── __init__.py
        └── router.py          # GET /health → {"status":"ok"}
```

### Pontos-chave da árvore

- **`main.py` é o único lugar onde tudo se encontra**. As factories `build_processor()`, `build_classifier()`, `build_color_detector()` são triviais e ficam aqui — sem container DI, sem mágica.
- **`modules/captures/` é o único módulo de domínio**. Toda a lógica de captura, classificação, detecção de cor e geração 3D vive aqui. O módulo `health` é só `/health`.
- **Tudo abaixo de `modules/` segue o padrão Feature-First**: cada módulo carrega seu próprio router, service, repository, models, schemas. Quando precisar de um módulo novo (ex.: histórico), siga o mesmo layout.
- **`blender_scripts/` é especial**: rodam **dentro** do Blender via `--python`. Não importam nada do `app/` (não conseguiriam — Blender tem o próprio Python isolado).

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
└── modules/
    ├── __init__.py
    └── captures/
        ├── __init__.py
        ├── test_classifier.py         # 11 testes — DisabledClassifier + CLIPClassifier mockado
        ├── test_color_detector.py     # 12 testes — AverageColorDetector + edge cases
        ├── test_customize_template.py # 6 testes — script Blender invocado com Blender real
        ├── test_processor.py          # 6 testes — FakeProcessor (cubo GLB válido)
        ├── test_queue.py              # 5 testes — ProcessingQueue assíncrona
        ├── test_router.py             # 5 testes — POST/GET via TestClient
        ├── test_service.py            # 11 testes — CaptureService (caminho feliz e erros)
        └── test_template_processor.py # 12 testes — TemplateProcessor (mocks + integração)
```

**Total: ~86 testes em 10 arquivos** (número aproximado; execute `pytest --collect-only` para o valor exato). Nenhum teste exige Postgres rodando; alguns exigem Blender (e são pulados se ausente). Detalhes em [14 - Testes](14-testes.md).

## `scripts/` — utilitários offline

```
scripts/
├── smoke.ps1                              # smoke test ponta a ponta via HTTP
├── build_feeling_label.py                 # gera PNG da label do Feelin' Flame com PIL
└── blender/                               # rodam dentro do Blender headless
    ├── inspect_raw_templates.py           # lista materiais/meshes dos GLBs brutos
    ├── normalize_template.py              # padroniza GLBs do Sketchfab
    ├── generate_feeling_template.py       # gera o template procedural V2
    └── preview_feeling_template.py        # render Cycles (PNG) do template
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
└── models/                        # gitignored
    ├── <job_id>.glb
    └── candidates/                # GLBs intermediários para debug (gitignored)
        └── <job_id>/
```

A pasta `storage/uploads/` e `storage/models/` são criadas no startup pelo `LocalStorage.ensure_dirs()` ([`app/storage/local_storage.py`](../app/storage/local_storage.py)). O `.gitignore` bloqueia `storage/uploads/`, `storage/models/`, `storage/*.glb`, `storage/*.gltf` — só o HTML do viewer é versionado.

## `docs/` — esta pasta

Conjunto **01–15** (Markdown) descrevendo o backend; o [README](README.md) desta pasta indica a ordem de leitura.

```
docs/
├── README.md
├── 01-visao-geral.md … 15-glossario.md
└── 04-estrutura-de-pastas.md   ← este ficheiro
```

## Convenções de import e organização

- **Imports absolutos a partir de `app/`** dentro do código (`from ...core.logging import get_logger`). Os `..` relativos só aparecem quando o ganho de legibilidade é claro.
- **Cada módulo expõe seu router via `from .router import router`**, e `main.py` faz `app.include_router(captures_router)`.
- **Arquivos `__init__.py` ficam vazios** — o agrupamento é por nome, não por re-export. Procure pelo arquivo final, não por barril.
- **Lazy imports para libs pesadas**: `transformers` em `classifier.py` e `Pillow` em `color_detector.py` são importados dentro dos métodos. Permite que o módulo seja importado mesmo sem essas deps instaladas (caso `CLASSIFIER_TYPE=disabled`).

## Próximas leituras

- Como as camadas conversam: [05 - Arquitetura](05-arquitetura.md).
- Detalhe do módulo principal: [08 - Módulo `captures`](08-modulo-captures.md).
