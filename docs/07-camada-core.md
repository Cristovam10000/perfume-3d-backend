# 07 — Camada `core` e configuração

Visão geral de arquivos “transversais” fora de `modules/captures/`.

## Settings

Referência de variáveis de ambiente (ficheiro de código: [`app/config.py`](../app/config.py), classe `Settings`).

- Baseado em **pydantic-settings**; lê `.env` com encoding UTF-8.
- Propriedades principais (nomes em **snake_case** no env; o Pydantic mapeia `DATABASE_URL` → `database_url` automaticamente):

| Campo (Python) | Variável env típica | Papel |
|----------------|--------------------|--------|
| `app_name` | `APP_NAME` | Título no OpenAPI |
| `app_host` / `app_port` | `APP_HOST`, `APP_PORT` | Bind Uvicorn |
| `database_url` | `DATABASE_URL` | `postgresql+asyncpg://...` |
| `storage_root` | `STORAGE_ROOT` | Raiz de uploads e models |
| `cors_origins` | `CORS_ORIGINS` | `*` ou lista separada por vírgula |
| `processor_type` | `PROCESSOR_TYPE` | `fake` \| `template` |
| `blender_executable` | `BLENDER_EXECUTABLE` | Caminho do `blender.exe` / binário |
| `templates_dir` | `TEMPLATES_DIR` | Pasta dos GLBs normalizados |
| `classifier_type` | `CLASSIFIER_TYPE` | `disabled` \| `clip` |
| `clip_model` | `CLIP_MODEL` | ID HuggingFace do CLIP |
| `default_template_id` | `DEFAULT_TEMPLATE_ID` | Template quando classifier desligado |
| `color_detector_type` | `COLOR_DETECTOR_TYPE` | `disabled` \| `average` |

- `cors_origin_list` — propriedade que expande `*` em lista usada pelo `CORSMiddleware`.
- `uploads_dir` / `models_dir` — derivados de `storage_root`.

> **Segredo**: o arquivo **`.env` real** não entra no Git (ver `.gitignore`). Use [`.env.example`](../.env.example) como modelo; ajuste senhas e caminhos localmente.

## `app/database.py`

- `create_async_engine(settings.database_url, pool_pre_ping=True)`.
- `SessionFactory` = `async_sessionmaker` com `expire_on_commit=False`.
- `Base` = `DeclarativeBase` (SQLAlchemy 2.0).
- `create_all()`: em transação, `Base.metadata.create_all` — usado no lifespan; importa `modules.captures.models` para registrar tabelas.

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
