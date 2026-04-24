# Perfume 3D — Backend

Backend FastAPI do MVP acadêmico de captura e reconstrução 3D de perfumes. O
app Flutter (`../front`) captura um lote de imagens, envia a este serviço, e
depois busca o modelo `.glb` gerado para renderizar no visualizador 3D.

## Stack

| Camada | Tecnologia |
|---|---|
| HTTP | FastAPI 0.115+ |
| ORM | SQLAlchemy async 2.0 + asyncpg |
| Banco | PostgreSQL 16 (container Docker `tcc-postgres`) |
| Worker 3D | Fila `asyncio.Queue` in-process |
| Pipeline 3D (fase 1) | `FakeProcessor` — gera cubo `.glb` sintético |
| Pipeline 3D (fase 2) | `MeshroomProcessor` com AliceVision + Blender (planejado) |
| Armazenamento | Disco local (`storage/uploads/`, `storage/models/`) |
| Testes | pytest, pytest-asyncio, httpx, aiosqlite |

## Arquitetura (resumo)

```
app/
  main.py                 # create_app() + production_lifespan
  config.py               # pydantic-settings (lê .env)
  database.py             # engine + SessionFactory async
  dependencies.py         # get_capture_service
  core/                   # exceptions, logging
  storage/                # LocalStorage (disco)
  modules/
    captures/             # módulo principal do fluxo 3D
      models.py           # CaptureJob, CaptureImage (SQLAlchemy)
      schemas.py          # DTOs (pydantic) com alias camelCase
      repository.py       # queries encapsuladas
      service.py          # orquestração das use cases
      router.py           # endpoints HTTP
      queue.py            # ProcessingQueue + worker
      processor.py        # ABC Processor + FakeProcessor
      status.py           # enum de estados
    health/router.py      # /health
storage/                  # gerado em runtime (git-ignorado)
tests/                    # pytest suite
```

**Separação de camadas:** `router → service → repository → database`. O
`processor` é uma ABC plugável: trocar `FakeProcessor` por `MeshroomProcessor`
é uma linha em `main.py`.

## Pré-requisitos

- **Python 3.12+** (foi desenvolvido com 3.14, mas 3.12 e 3.13 também funcionam)
- **Docker** para rodar o Postgres
- **Git**

## Setup

### 1. Postgres

Este projeto assume o container `tcc-postgres` na porta `5433` com banco `tcc`
e credenciais `postgres/postgres`. Se ainda não tem:

```powershell
docker run -d `
  --name tcc-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=tcc `
  -p 5433:5432 `
  postgres:16
```

Se já existe mas está parado:

```powershell
docker start tcc-postgres
```

### 2. Ambiente Python

```powershell
# criar venv e ativar
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# instalar deps (runtime + dev)
pip install -r requirements-dev.txt
```

### 3. Variáveis de ambiente

```powershell
Copy-Item .env.example .env
```

O `.env` default já aponta para `postgresql+asyncpg://postgres:postgres@localhost:5433/tcc`.

### 4. Subir o servidor

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

O lifespan cria as tabelas (`create_all()`) na primeira subida, garante os
diretórios `storage/uploads/` e `storage/models/`, e inicia o worker da fila.

**Onde acessar:**

| URL | Uso |
|---|---|
| http://localhost:8000/health | Liveness check |
| http://localhost:8000/docs | Swagger UI (interativo) |
| http://localhost:8000/redoc | ReDoc |
| http://10.0.2.2:8000 | Base URL para o app Flutter em **emulador Android** |
| http://&lt;IP-da-maquina&gt;:8000 | Base URL para o app em **device físico** na mesma Wi-Fi |

Para device físico, ajuste `backendBaseUrl` em
[`../front/lib/core/constants/app_constants.dart`](../front/lib/core/constants/app_constants.dart)
e libere a porta 8000 no firewall do Windows.

## Endpoints

### `POST /captures`

Cria um job de reconstrução 3D a partir de um lote de imagens.

- **Content-Type:** `multipart/form-data`
- **Campo:** `images` (1..N arquivos binários JPEG)
- **Resposta 201:** `{ "jobId": "<uuid>" }`
- **Erros:** `422` se nenhuma imagem for enviada.

### `GET /captures/{jobId}/status`

Consulta o estado atual do processamento.

- **Resposta 200:**
  ```json
  {
    "status": "waiting|processing|completed|error",
    "message": "Reconstruindo modelo 3D",
    "modelUrl": "http://host:8000/files/models/<jobId>.glb",
    "error": null
  }
  ```
- **Resposta 404:** se o `jobId` não existir.

Quando `status == "completed"`, o campo `modelUrl` aponta para o `.glb`
servido por `StaticFiles` (`/files/...`). O URL absoluto é construído em
tempo de resposta usando `request.base_url`, então o mesmo DB funciona para
emulador (`10.0.2.2`) e device físico (IP da LAN) sem reconfiguração.

### `GET /health`

Liveness simples: `{ "status": "ok" }`.

### `GET /files/{path}`

Static files servindo o conteúdo de `storage/`. Uso interno: o front carrega
o `.glb` via este path. Não precisa ser chamado diretamente pelo app.

## Rodar os testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Cobertura atual (24 testes):

- `test_processor.py` — geração válida de GLB (6)
- `test_queue.py` — worker assíncrono, cancelamento, resiliência (5)
- `test_service.py` — `create_job`, `process_job`, caminhos felizes e de erro (5)
- `test_router.py` — `POST /captures`, `GET .../status`, 404, camelCase (5)
- `test_main.py` — end-to-end via `httpx.AsyncClient` (3)

Os testes usam SQLite (`aiosqlite`) em arquivo temporário, sem exigir
Postgres rodando.

## Smoke test (servidor real)

Com o backend no ar, teste o fluxo completo via HTTP:

### PowerShell

```powershell
.\scripts\smoke.ps1
```

O script sobe uma requisição com 2 imagens de teste, faz polling do status
até `completed`, baixa o `.glb` retornado e valida o magic header `glTF`.

### curl (referência)

```bash
# 1) upload
curl -F "images=@foto1.jpg" -F "images=@foto2.jpg" http://localhost:8000/captures
# => {"jobId":"<uuid>"}

# 2) status (repetir até status=completed)
curl http://localhost:8000/captures/<uuid>/status

# 3) baixar o modelo
curl -o cubo.glb http://localhost:8000/files/models/<uuid>.glb
```

## Estados do job

Os nomes são **idênticos** ao que o parser do Flutter reconhece em
[`processing_job.dart:64`](../front/lib/features/processing/domain/processing_job.dart#L64).

| Estado | Significado |
|---|---|
| `waiting` | Job criado, aguardando worker puxar da fila |
| `processing` | Worker executando o pipeline 3D |
| `completed` | `.glb` gerado e servido — `modelUrl` preenchido |
| `error` | Pipeline falhou — `error` preenchido com a mensagem |

## Roadmap

- [x] Fase 1 — MVP funcional ponta a ponta com `FakeProcessor` (cubo sintético)
- [ ] Fase 2 — Integração com **Meshroom/AliceVision** (reconstrução real)
  - [ ] `MeshroomProcessor` chamando `meshroom_batch` via subprocess
  - [ ] Conversão `.obj` → `.glb` via Blender headless
  - [ ] Feature flag `PROCESSOR_TYPE=fake|meshroom` no `.env`
  - [ ] Progresso granular na tela de processing (etapa do pipeline)
- [ ] Futuro — migrações com Alembic (hoje é `create_all` no startup)
- [ ] Futuro — endpoint `GET /captures/history` + tela de histórico no app
- [ ] Futuro — migrar storage local para object storage (S3/Firebase)

## Licença

Projeto acadêmico — TCC.
