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
| Pipeline 3D (default) | `IntegratedPipeline` — preprocess + rembg + cache CLIP + Hunyuan3D + refiner + label |
| Geração 3D (IA) | Hunyuan3D-2mv (container Docker + GPU) via cliente `httpx` |
| Cache de modelos | similaridade CLIP (cosine) sobre `modelos_3d_universais` |
| Pós-processamento | Blender 5.1 headless (vidro PBR, limpeza, decal da label) |
| Modos alternativos | `FakeProcessor` (cubo, p/ testes) · `TemplateProcessor` (Blender + GLB pronto) |
| Armazenamento | Disco local (`storage/uploads/`, `storage/models/`, `storage/cache/`) |
| Módulo comercial | `/sales/*` (clientes, produtos, vendas) sobre o mesmo Postgres |
| Testes | pytest, pytest-asyncio, httpx, aiosqlite |

## Arquitetura (resumo)

```
app/
  main.py                 # create_app() + production_lifespan + factories (build_pipeline)
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
      service.py          # orquestração (magra) das use cases
      router.py           # endpoints HTTP
      queue.py            # ProcessingQueue + worker
      processor.py        # ABC Processor + Fake/Template/Hunyuan3DProcessor
      pipeline.py         # IntegratedPipeline (composição dos stages — default)
      cache.py            # ClipSimilarityCache + embeddings.py / modelos_universais.py
      *_remover/refiner/extractor/projector.py  # stages do pipeline IA
      status.py           # enum de estados
    sales/                # módulo comercial (/sales/*)
    health/router.py      # /health
storage/                  # gerado em runtime (git-ignorado)
tests/                    # pytest suite
```

**Separação de camadas:** `router → service → pipeline → storage/DB`. O `Processor`
é uma ABC plugável: `PIPELINE_MODE` (`fake` | `template` | `integrated`) escolhe a
implementação raiz em `build_pipeline()`, e **cada stage** do pipeline IA também é uma
Strategy ligada/desligada pelo `.env`. Documentação detalhada e didática em [`docs/`](docs/README.md).

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
- **Campos:** `images` (1..N arquivos binários JPEG); `views` (opcional, rótulos de vista paralelos); `productId` (opcional, amarra o GLB a um produto de `/sales`)
- **Resposta 201:** `{ "jobId": "<uuid>" }`
- **Erros:** `422` se nenhuma imagem for enviada.

> Contrato HTTP completo (incl. `/sales/*`) em [docs/13 — Endpoints HTTP](docs/13-endpoints-http.md).

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

Cobertura atual: **285 testes** (`pytest --collect-only`), distribuídos entre o módulo
`captures` (pipeline, cache, stages, router, service, fila — ~196), a suíte de avaliação
`tests/eval/` (métricas geométricas — 52), os templates normalizados (25) e os testes
end-to-end (`test_main.py` — 11).

Os testes usam SQLite (`aiosqlite`) em arquivo temporário, sem exigir Postgres rodando;
componentes que dependem de Blender/rembg/CLIP/Hunyuan são **pulados** quando essas
dependências faltam. Detalhes em [docs/14 — Testes](docs/14-testes.md).

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

- [x] MVP ponta a ponta com `FakeProcessor` (cubo sintético).
- [x] Caminho de templates Blender (`TemplateProcessor`) — hoje usado como **fallback**.
- [x] **Pipeline de IA integrado** (`IntegratedPipeline`): Hunyuan3D + pré-proc + rembg + refiner + label.
- [x] **Cache global** por similaridade CLIP (`modelos_3d_universais`, cross-tenant) + `productId` opcional.
- [x] Módulo comercial `/sales/*` (clientes, produtos, vendas).
- [x] Suíte de **avaliação quantitativa** comparando IA × templates × fotogrametria (ver [eval/](eval/README.md)).
- [ ] Calibrar `CACHE_SIMILARITY_THRESHOLD` com dataset real.
- [ ] Migrações com Alembic (hoje é `create_all` + `ensure_*_schema` no startup).
- [ ] Endpoint `GET /captures/history` + endpoints admin do cache.
- [ ] Migrar storage local para object storage (S3/Firebase).

> Fotogrametria (Meshroom/AliceVision) foi **avaliada e descartada** para o pipeline de
> produção — vidro e superfícies reflexivas quebram a correspondência de pontos. Permanece
> como **branch de comparação** na suíte `eval/`.

## Licença

Projeto acadêmico — TCC.
