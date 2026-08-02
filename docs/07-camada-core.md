# 07 — Camada `core` e configuração

> **O que você vai aprender neste doc**
> - Todas as variáveis de ambiente do backend, agrupadas por tema, e o papel de cada uma.
> - Como `pydantic-settings` lê o `.env` e valida valores com `Literal`.
> - Os blocos transversais: `database`, `dependencies`, `core/exceptions`, `core/logging`.
>
> **Pré-requisitos:** [02 - Stack tecnológico](02-stack-tecnologico.md). Código-fonte: [`app/config.py`](../app/config.py).

Visão geral de arquivos “transversais” fora de `modules/captures/`.

## Settings

Referência de variáveis de ambiente (ficheiro de código: [`app/config.py`](../app/config.py), classe `Settings`).

- Baseado em **pydantic-settings**; lê `.env` com encoding UTF-8.
- Propriedades principais (nomes em **snake_case** no env; o Pydantic mapeia `DATABASE_URL` → `database_url` automaticamente):

### Núcleo (infra e CORS)

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `app_name` | `APP_NAME` | Título no OpenAPI |
| `app_host` / `app_port` | `APP_HOST`, `APP_PORT` | Bind Uvicorn |
| `database_url` | `DATABASE_URL` | `postgresql+asyncpg://...` |
| `storage_root` | `STORAGE_ROOT` | Raiz de uploads, models e cache |
| `cors_origins` | `CORS_ORIGINS` | `*` ou lista separada por vírgula |

### Pipeline 3D

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `pipeline_mode` | `PIPELINE_MODE` | `fake` \| `integrated` (default) |
| `blender_executable` | `BLENDER_EXECUTABLE` | Caminho do `blender.exe` / binário |

### Hunyuan (cliente HTTP)

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `hunyuan_url` | `HUNYUAN_URL` | URL base do contêiner Hunyuan (default `http://localhost:7860`) |
| `hunyuan_timeout_seconds` | `HUNYUAN_TIMEOUT_SECONDS` | Timeout do cliente em segundos (default 1200) |
| `hunyuan_octree_resolution` | `HUNYUAN_OCTREE_RESOLUTION` | Default 384 |
| `hunyuan_num_inference_steps` | `HUNYUAN_NUM_INFERENCE_STEPS` | Default 75 |
| `hunyuan_guidance_scale` | `HUNYUAN_GUIDANCE_SCALE` | Default 7.5 |
| `hunyuan_mc_algo` | `HUNYUAN_MC_ALGO` | `mc` (default) ou `dmc` |
| `hunyuan_texture_resolution` | `HUNYUAN_TEXTURE_RESOLUTION` | Default 2048 |

### Cache de modelos

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `cache_enabled` | `CACHE_ENABLED` | Liga/desliga o cache inteiro (default `true`) |
| `cache_similarity_threshold` | `CACHE_SIMILARITY_THRESHOLD` | Cosine acima do qual um lookup vira hit (default 0.92) |
| `cache_embedder_type` | `CACHE_EMBEDDER_TYPE` | `disabled` \| `clip` |
| `cache_embedding_model` | `CACHE_EMBEDDING_MODEL` | ID HuggingFace do CLIP (default `openai/clip-vit-base-patch32`) |

### Stages do pipeline IA

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `image_preprocessor_type` | `IMAGE_PREPROCESSOR_TYPE` | `disabled` \| `standard` |
| `background_remover_type` | `BACKGROUND_REMOVER_TYPE` | `disabled` \| `rembg` |
| `mesh_refiner_type` | `MESH_REFINER_TYPE` | `disabled` \| `blender` (default `blender` — shader de vidro PBR) |
| `label_extractor_type` | `LABEL_EXTRACTOR_TYPE` | `disabled` \| `homography` |
| `label_upscaler_type` | `LABEL_UPSCALER_TYPE` | `disabled` \| `lanczos` |
| `label_projector_type` | `LABEL_PROJECTOR_TYPE` | `disabled` \| `blender` |
| `label_front_axis` | `LABEL_FRONT_AXIS` | `front_y_neg` (default), etc. |
| `label_min_confidence` | `LABEL_MIN_CONFIDENCE` | 0.0–1.0 (default 0.3) |
| `top_projector_type` | `TOP_PROJECTOR_TYPE` | `disabled` \| `blender` (default). Só dispara quando o app rotula uma foto como `top`. |
| `top_cosine_threshold` | `TOP_COSINE_THRESHOLD` | Cosseno mínimo entre a normal da face e o eixo Z para contar como topo (default 0.45). |
| `label_target_size` | `LABEL_TARGET_SIZE` | Pixels do Lanczos (default 2048) |

### Legado / opcional

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `color_detector_type` | `COLOR_DETECTOR_TYPE` | `disabled` (default) \| `average`. Legado do `TemplateProcessor` (removido); nenhum stage lê essa chave hoje. |
| `clip_model` | `CLIP_MODEL` | Mantido por compatibilidade. Equivalente a `CACHE_EMBEDDING_MODEL` quando `cache_embedder_type=clip`. |
| `classifier_type` | `CLASSIFIER_TYPE` | Legado. Lido com aviso de deprecation; substituído por `cache_embedder_type`. |
| `processor_type` | `PROCESSOR_TYPE` | Legado. Lido com aviso de deprecation; só `fake`/`integrated` são mapeados — `template` caiu para o default. |

- `cors_origin_list` — propriedade que expande `*` em lista usada pelo `CORSMiddleware`.
- `uploads_dir` / `models_dir` / `cache_dir` — derivados de `storage_root`.

> **Segredo**: o arquivo **`.env` real** não entra no Git (ver `.gitignore`). Use [`.env.example`](../.env.example) como modelo; ajuste senhas e caminhos localmente.

## `app/database.py`

- `create_async_engine(settings.database_url, pool_pre_ping=True)`.
- `SessionFactory` = `async_sessionmaker` com `expire_on_commit=False`.
- `Base` = `DeclarativeBase` (SQLAlchemy 2.0).
- `create_all()`: em transação, `Base.metadata.create_all` — usado no lifespan; importa `modules.captures.models` e `modules.captures.modelos_universais` para registrar todas as tabelas (`capture_jobs`, `capture_images`, `modelos_3d_universais`).

## `app/dependencies.py`

- `get_capture_service(request)`: retorna `request.app.state.capture_service` ou levanta `RuntimeError` se o lifespan não rodou. Evita singleton global e facilita testes com múltiplas apps.

## `app/core/exceptions.py`

- `AppError` (base, HTTP 400), `NotFoundError` (404), `ValidationError` (422).
- `register_exception_handlers(app)` mapeia para JSON `{"error": "mensagem"}`.

## `app/core/logging.py`

- `configure_logging()` e `get_logger(name)` — logs estruturados usados em `queue`, `service`, `classifier`, etc.

## `app/storage/local_storage.py`

- Detalhado em [12 — Armazenamento e banco](12-armazenamento-e-banco.md) (pasta, paths públicos, convenção de nomes).

## Leituras relacionadas

- [02 — Stack tecnológico](02-stack-tecnologico.md) (versões de libs)
- [03 — Inicialização do projeto](03-inicializacao-do-projeto.md) (exemplo de `.env`)
