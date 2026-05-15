# Backend

## Visao geral

O backend em `back/` e uma aplicacao FastAPI que expoe health check, captura/processamento 3D, API comercial `/sales/*` e arquivos estaticos locais (fonte: `back/app/main.py`). A aplicacao cria tabelas SQLAlchemy do modulo `captures`, aplica compatibilidade incremental no schema comercial e inicializa uma fila assíncrona para processamento de jobs (fontes: `back/app/main.py`, `back/app/database.py`, `back/app/modules/sales/repository.py`, `back/app/modules/captures/queue.py`).

## Por que existe

O backend concentra o contrato HTTP consumido pelo Flutter e isola as responsabilidades de persistencia, storage local, processamento 3D e regras comerciais sobre clientes/produtos/vendas (fontes: `back/app/modules/captures/router.py`, `back/app/modules/captures/service.py`, `back/app/modules/sales/router.py`, `back/app/modules/sales/repository.py`).

## Stack/dependencias

| Grupo | Dependencias | Fontes |
|---|---|---|
| Runtime HTTP | `fastapi`, `uvicorn[standard]`, `python-multipart` | `back/requirements.txt` |
| Config/DTO | `pydantic`, `pydantic-settings` | `back/requirements.txt`, `back/app/config.py` |
| Banco | `sqlalchemy[asyncio]`, `asyncpg`, `greenlet` | `back/requirements.txt`, `back/app/database.py` |
| Cliente HTTP interno | `httpx` para `Hunyuan3DProcessor` | `back/requirements.txt`, `back/app/modules/captures/processor.py` |
| Testes | `pytest`, `pytest-asyncio`, `httpx`, `aiosqlite` | `back/requirements-dev.txt`, `back/pytest.ini`, `back/tests/conftest.py` |
| Opcionais de visao | `rembg`, `onnxruntime`, `opencv-python`, `numpy`, `pillow` | `back/requirements-vision.txt` |
| Opcionais de classificador | `torch`, `transformers`, `pillow` | `back/requirements-classifier.txt` |

## Estrutura

```text
back/app/
  main.py
  config.py
  database.py
  dependencies.py
  core/
    exceptions.py
    logging.py
  storage/
    local_storage.py
  modules/
    health/router.py
    captures/
      router.py
      service.py
      repository.py
      models.py
      schemas.py
      processor.py
      queue.py
      classifier.py
      color_detector.py
      blender_scripts/
    sales/
      router.py
      repository.py
      schemas.py
```

Endpoints principais:

| Metodo | Caminho | Funcao | Fontes |
|---|---|---|---|
| GET | `/health` | Liveness simples `{ "status": "ok" }` | `back/app/modules/health/router.py` |
| POST | `/captures` | Recebe `images` multipart e cria job | `back/app/modules/captures/router.py` |
| GET | `/captures/{job_id}/status` | Retorna status, mensagem, `modelUrl` e erro | `back/app/modules/captures/router.py`, `back/app/modules/captures/schemas.py` |
| GET | `/sales/snapshot` | Snapshot comercial completo | `back/app/modules/sales/router.py`, `back/app/modules/sales/schemas.py` |
| POST | `/sales/products` | Cria produto | `back/app/modules/sales/router.py`, `back/app/modules/sales/repository.py` |
| PATCH | `/sales/products/{product_id}/stock` | Ajusta estoque por `add` ou `set` | `back/app/modules/sales/router.py`, `back/app/modules/sales/schemas.py` |
| POST | `/sales/sales` | Cria venda e parcelas | `back/app/modules/sales/router.py`, `back/app/modules/sales/repository.py` |

Variaveis de ambiente confirmadas:

| Variavel | Default/exemplo | Uso | Fontes |
|---|---|---|---|
| `APP_NAME` | `perfume-3d-backend` | Titulo FastAPI | `back/.env.example`, `back/app/config.py` |
| `APP_ENV` | `development` | Ambiente | `back/.env.example`, `back/app/config.py` |
| `APP_HOST` | `0.0.0.0` | Host de execucao recomendado | `back/.env.example`, `back/app/config.py` |
| `APP_PORT` | `8000` | Porta recomendada | `back/.env.example`, `back/app/config.py` |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5433/tcc` | Conexao Postgres | `back/.env.example`, `back/app/config.py`, `back/app/database.py` |
| `STORAGE_ROOT` | `./storage` | Uploads e modelos gerados | `back/.env.example`, `back/app/config.py`, `back/app/storage/local_storage.py` |
| `CORS_ORIGINS` | `*` | CORS | `back/.env.example`, `back/app/main.py` |
| `PROCESSOR_TYPE` | `fake` | `fake` ou `template` | `back/.env.example`, `back/app/config.py`, `back/app/main.py` |
| `BLENDER_EXECUTABLE` | caminho Windows do Blender 5.1 | Usado pelo `TemplateProcessor` | `back/.env.example`, `back/app/config.py`, `back/app/modules/captures/processor.py` |
| `TEMPLATES_DIR` | `./assets/templates/normalized` | GLBs normalizados | `back/.env.example`, `back/app/config.py` |
| `CLASSIFIER_TYPE` | `disabled` | `disabled` ou `clip` | `back/.env.example`, `back/app/config.py`, `back/app/main.py` |
| `COLOR_DETECTOR_TYPE` | `disabled` | `disabled` ou `average` | `back/.env.example`, `back/app/config.py`, `back/app/main.py` |

## Como rodar/usar

Setup local esperado:

```powershell
cd C:\TCC\back
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Subir o Postgres:

```powershell
cd C:\TCC
docker compose up -d postgres
```

Subir o backend:

```powershell
cd C:\TCC\back
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Smoke basico:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Testes:

```powershell
cd C:\TCC\back
.\.venv\Scripts\python.exe -m pytest
```

Esses comandos seguem os arquivos de requisitos e o contrato de inicializacao atual; qualquer instalacao de dependencia deve ser feita com aprovacao do responsavel pelo ambiente (fontes: `back/requirements-dev.txt`, `back/.env.example`, `back/pytest.ini`).

## Pontos de atencao

- O backend nao e containerizado no `docker-compose.yml`; ele deve ser rodado localmente com Uvicorn, salvo se for criado um Dockerfile especifico no futuro (fonte: `docker-compose.yml`).
- `create_all()` registra apenas modelos SQLAlchemy importados pelo modulo `captures`; o schema comercial inteiro nao e criado por ORM (fontes: `back/app/database.py`, `back/app/modules/captures/models.py`, `back/app/modules/sales/repository.py`).
- `ensure_sales_schema()` usa `ALTER TABLE IF EXISTS` e nao cria tabelas comerciais do zero (fonte: `back/app/modules/sales/repository.py`).
- `Hunyuan3DProcessor` existe, mas nao e retornado pela factory `build_processor()`; para usa-lo no runtime principal seria preciso alterar `Settings.processor_type` e `build_processor()` (fontes: `back/app/config.py`, `back/app/main.py`, `back/app/modules/captures/processor.py`).
- O `FakeProcessor` gera um cubo GLB sintetico; o `TemplateProcessor` invoca Blender headless sobre GLBs normalizados (fonte: `back/app/modules/captures/processor.py`).

