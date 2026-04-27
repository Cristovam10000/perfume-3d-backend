# 02 — Stack tecnológico

A fonte canônica das dependências é [`requirements.txt`](../requirements.txt) (runtime), [`requirements-dev.txt`](../requirements-dev.txt) (testes) e [`requirements-classifier.txt`](../requirements-classifier.txt) (CLIP, opcional).

## Versões e SDK

```
Python 3.12+ (desenvolvido em 3.14, 3.12 e 3.13 também funcionam)
Blender 5.1+ (necessário se PROCESSOR_TYPE=template)
PostgreSQL 16 (container Docker `tcc-postgres`)
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
- **`pydantic-settings`** — `Settings` em [`app/config.py`](../app/config.py) lê `.env` automaticamente. Usa `Literal` para `PROCESSOR_TYPE` (`fake` \| `template`), `CLASSIFIER_TYPE` (`disabled` \| `clip`) e `COLOR_DETECTOR_TYPE` (`disabled` \| `average`).

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

## Dependências do classificador (opcionais) — [`requirements-classifier.txt`](../requirements-classifier.txt)

```
torch>=2.4
transformers>=4.45
pillow>=10.0
```

Instaladas só quando `CLASSIFIER_TYPE=clip` ou `COLOR_DETECTOR_TYPE=average` no `.env`. Custo de download: **~2GB** entre `torch` e os pesos do CLIP. Em CPU funciona, mas RTX 5050+ acelera ~10x.

- **`torch` 2.4+** — backend do CLIP.
- **`transformers` 4.45+** — `CLIPModel`, `CLIPProcessor`. Imports são lazy em [`app/modules/captures/classifier.py`](../app/modules/captures/classifier.py): só carregam se `CLIPClassifier` for instanciado.
- **`pillow` 10.0+** — usado pelo `AverageColorDetector` em [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py) para abrir imagens (`Image.open`, `ImageOps.exif_transpose`) e respeitar EXIF orientation.

## Ferramentas externas (não-Python)

- **Blender 5.1+** — invocado como subprocess pelo `TemplateProcessor` ([`app/modules/captures/processor.py`](../app/modules/captures/processor.py)). Caminho default em Windows: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`. Configurável via `BLENDER_EXECUTABLE` no `.env`.
- **PostgreSQL 16** — container Docker oficial. Configurado em `DATABASE_URL`.
- **Docker** — apenas para subir o Postgres em dev. O backend em si não é containerizado (ainda).

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
| Pipeline 3D | Blender 5.1 headless via subprocess | [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) + [`app/modules/captures/blender_scripts/customize_template.py`](../app/modules/captures/blender_scripts/customize_template.py) |
| Classificador | OpenAI CLIP via transformers (opt-in) | [`app/modules/captures/classifier.py`](../app/modules/captures/classifier.py) |
| Detector de cor | Pillow + heurística RGB (opt-in) | [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py) |
| Storage | filesystem local | [`app/storage/local_storage.py`](../app/storage/local_storage.py) |
| Static serving | `fastapi.staticfiles.StaticFiles` | mount `/files` e `/templates` em [`app/main.py`](../app/main.py) |
| Testes | pytest 8.3 + pytest-asyncio 0.24 | [`tests/`](../tests/), [`pytest.ini`](../pytest.ini) |
| HTTP test client | httpx 0.27 (`AsyncClient`) | [`tests/test_main.py`](../tests/test_main.py) |
| DB de teste | SQLite + aiosqlite | fixture `session_factory` em [`tests/conftest.py`](../tests/conftest.py) |

## Próximas leituras

- Como instalar e rodar tudo: [03 - Inicialização do projeto](03-inicializacao-do-projeto.md).
- Quem importa o quê em qual ordem: [05 - Arquitetura](05-arquitetura.md).
