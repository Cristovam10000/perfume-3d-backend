# 02 — Stack tecnológico

A fonte canônica das dependências é [`requirements.txt`](../requirements.txt) (runtime), [`requirements-dev.txt`](../requirements-dev.txt) (testes) e [`requirements-classifier.txt`](../requirements-classifier.txt) (CLIP, opcional).

## Versões e SDK

```
Python 3.12+ (desenvolvido em 3.14, 3.12 e 3.13 também funcionam)
Blender 5.1+ (necessário em PIPELINE_MODE=integrated ou template)
PostgreSQL 16 (container Docker `tcc-postgres`)
NVIDIA GPU + Docker NVIDIA Container Toolkit (necessário em PIPELINE_MODE=integrated)
```

## Dependências runtime — [`requirements.txt`](../requirements.txt)

```
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.10
pydantic-settings>=2.6
python-multipart>=0.0.20
sqlalchemy[asyncio]>=2.0.36
asyncpg>=0.30
greenlet>=3.2
```

### Camada HTTP

- **`fastapi`** — framework web. Usa `APIRouter` em [`app/modules/captures/router.py`](../app/modules/captures/router.py) e [`app/modules/health/router.py`](../app/modules/health/router.py), `Depends` para injeção do `CaptureService`, e `lifespan` async para bootstrap em [`app/main.py`](../app/main.py).
- **`uvicorn[standard]`** — servidor ASGI. O `[standard]` traz `httptools` (HTTP parser em C), `uvloop` (no Linux/Mac), e `watchfiles` (auto-reload em dev).
- **`python-multipart`** — necessário para `UploadFile` em `multipart/form-data` no `POST /captures`.

### Configuração e validação

- **`pydantic` 2.10+** — modelos de request/response em [`app/modules/captures/schemas.py`](../app/modules/captures/schemas.py), com `serialization_alias` para camelCase (`jobId`, `modelUrl`).
- **`pydantic-settings`** — `Settings` em [`app/config.py`](../app/config.py) lê `.env` automaticamente. Usa `Literal` para `PIPELINE_MODE` (`fake` \| `template` \| `integrated`), além das chaves de cada stage do pipeline integrado (`BACKGROUND_REMOVER_TYPE`, `IMAGE_PREPROCESSOR_TYPE`, `MESH_REFINER_TYPE`, `LABEL_EXTRACTOR_TYPE`, etc.). Compatibilidade preservada: `PROCESSOR_TYPE` antigo ainda é lido com aviso de deprecation.

### ORM e banco

- **`sqlalchemy[asyncio]` 2.0.36+** — ORM declarativo com `Mapped`/`mapped_column` (estilo 2.0). Sessions assíncronas em [`app/database.py`](../app/database.py).
- **`asyncpg`** — driver async para Postgres (URL `postgresql+asyncpg://...`).
- **`greenlet`** — dependência transitiva de `sqlalchemy[asyncio]`. Algumas operações ORM precisam dele para funcionar com async.

## Dependências de desenvolvimento — [`requirements-dev.txt`](../requirements-dev.txt)

```
-r requirements.txt

pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
aiosqlite>=0.20
```

- **`pytest` + `pytest-asyncio`** — runner de testes com modo async automático (configurado em [`pytest.ini`](../pytest.ini): `asyncio_mode = auto`).
- **`httpx`** — cliente HTTP usado pelo `httpx.AsyncClient` em testes end-to-end de [`tests/test_main.py`](../tests/test_main.py).
- **`aiosqlite`** — driver SQLite async usado pela fixture `session_factory` em [`tests/conftest.py`](../tests/conftest.py). **Os testes não precisam de Postgres rodando** — usam SQLite em arquivo temporário (`tmp_path`).

## Dependências do CLIP (embedder do cache) — [`requirements-classifier.txt`](../requirements-classifier.txt)

```
torch>=2.4
transformers>=4.45
pillow>=10.0
```

Instaladas quando `CACHE_EMBEDDER_TYPE=clip` (default no `PIPELINE_MODE=integrated`) ou `COLOR_DETECTOR_TYPE=average` no `.env`. Custo de download: **~2GB** entre `torch` e os pesos do CLIP. Em CPU funciona, mas RTX 5050+ acelera ~10x.

- **`torch` 2.4+** — backend do CLIP.
- **`transformers` 4.45+** — `CLIPModel`, `CLIPProcessor`. Imports são lazy em [`app/modules/captures/embeddings.py`](../app/modules/captures/embeddings.py): só carregam se `ClipImageEmbedder` for instanciado.
- **`pillow` 10.0+** — usado pelo embedder para abrir imagens (`Image.open`, `ImageOps.exif_transpose`) e respeitar EXIF orientation, e pelo `AverageColorDetector` quando ativo.

## Dependências de visão computacional — [`requirements-vision.txt`](../requirements-vision.txt)

```
rembg>=2.0.50
opencv-python>=4.10
numpy>=1.26
pillow>=10.0
```

Instaladas quando o `IntegratedPipeline` está ativo. `rembg` baixa ~200MB de pesos ONNX na primeira execução; `opencv-python` (~50MB) é usado pelo `HomographyLabelExtractor` e pelo `StandardImagePreprocessor`. Ver [10b](10b-segmentacao-e-label.md) e [09d](09d-preprocessamento-e-cleanup.md).

## Hunyuan3D (em contêiner Docker — não Python do backend)

O contêiner `perfume-hunyuan` em [`C:\TCC\docker\hunyuan`](../../docker/hunyuan) tem suas próprias dependências (`torch`, `diffusers`, `Hunyuan3D-2GP`, `mmgp`, etc.) — o backend Python **não importa nada disso**. A comunicação é puramente HTTP multipart via `httpx.AsyncClient`. Ver [09b](09b-pipeline-ai-hunyuan.md).

## Ferramentas externas (não-Python)

- **Blender 5.1+** — invocado como subprocess pelo `TemplateProcessor`, `BlenderMeshCleaner`, `BlenderMeshRefiner` e `BlenderLabelProjector`. Caminho default em Windows: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`. Configurável via `BLENDER_EXECUTABLE` no `.env`.
- **PostgreSQL 16** — container Docker oficial (`tcc-postgres`). Configurado em `DATABASE_URL`.
- **Docker + NVIDIA Container Toolkit** — usado para Postgres e para o serviço Hunyuan3D-2mv (contêiner `perfume-hunyuan`, GPU NVIDIA, ~6-8GB VRAM com profile mmgp 4). O backend em si não é containerizado.

## Stack por camada — visão consolidada

| Camada | Tecnologia | Onde é usada |
|---|---|---|
| HTTP | FastAPI 0.115+ | [`app/main.py`](../app/main.py), `app/modules/*/router.py` |
| ASGI server | Uvicorn 0.32+ | comando `uvicorn app.main:app` |
| Validação/DTO | Pydantic 2.10+ | [`app/modules/captures/schemas.py`](../app/modules/captures/schemas.py) |
| Config | pydantic-settings 2.6+ | [`app/config.py`](../app/config.py) |
| ORM | SQLAlchemy 2.0.36+ async | [`app/database.py`](../app/database.py), [`app/modules/captures/models.py`](../app/modules/captures/models.py), `repository.py` |
| Driver DB | asyncpg 0.30+ | URL `postgresql+asyncpg://...` |
| Banco | PostgreSQL 16 | container Docker `tcc-postgres` |
| Worker | `asyncio.Queue` (stdlib) | [`app/modules/captures/queue.py`](../app/modules/captures/queue.py) |
| Pipeline 3D (orquestração) | `IntegratedPipeline` (Python) | [`app/modules/captures/pipeline.py`](../app/modules/captures/pipeline.py) (planejado) |
| Geração 3D (IA) | Hunyuan3D-2mv via container Docker + GPU | [`docker/hunyuan/server.py`](../../docker/hunyuan/server.py), cliente HTTP em [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) |
| Geração 3D (fallback) | Blender 5.1 headless via subprocess | [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) (`TemplateProcessor`) + [`app/modules/captures/blender_scripts/customize_template.py`](../app/modules/captures/blender_scripts/customize_template.py) |
| Embedder CLIP (cache) | OpenAI CLIP via transformers | [`app/modules/captures/embeddings.py`](../app/modules/captures/embeddings.py) (planejado), reutilizando o modelo em [`app/modules/captures/classifier.py`](../app/modules/captures/classifier.py) |
| Cache de modelos | Cosine vs embedding 512-d | [`app/modules/captures/cache.py`](../app/modules/captures/cache.py) (planejado), [`app/modules/captures/modelos_3d_universais.py`](../app/modules/captures/modelos_3d_universais.py) (planejado) |
| Remoção de fundo | `rembg` + ONNX | [`app/modules/captures/background_remover.py`](../app/modules/captures/background_remover.py) |
| Extração de label | OpenCV (Canny + warpPerspective) | [`app/modules/captures/label_extractor.py`](../app/modules/captures/label_extractor.py) |
| Refinamento de mesh | Blender 5.1 headless | [`app/modules/captures/mesh_refiner.py`](../app/modules/captures/mesh_refiner.py) + [`app/modules/captures/blender_scripts/refine_ai_mesh.py`](../app/modules/captures/blender_scripts/refine_ai_mesh.py) |
| Detector de cor | Pillow + heurística RGB (legado/opcional) | [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py) |
| Storage | filesystem local | [`app/storage/local_storage.py`](../app/storage/local_storage.py) |
| Static serving | `fastapi.staticfiles.StaticFiles` | mount `/files` e `/templates` em [`app/main.py`](../app/main.py) |
| Testes | pytest 8.3 + pytest-asyncio 0.24 | [`tests/`](../tests/), [`pytest.ini`](../pytest.ini) |
| HTTP test client | httpx 0.27 (`AsyncClient`) | [`tests/test_main.py`](../tests/test_main.py) |
| DB de teste | SQLite + aiosqlite | fixture `session_factory` em [`tests/conftest.py`](../tests/conftest.py) |

## Próximas leituras

- Como instalar e rodar tudo: [03 - Inicialização do projeto](03-inicializacao-do-projeto.md).
- Quem importa o quê em qual ordem: [05 - Arquitetura](05-arquitetura.md).
