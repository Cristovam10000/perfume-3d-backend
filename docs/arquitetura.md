# Arquitetura

## Visao geral

A arquitetura atual combina dois repositorios irmaos: o app Flutter em `perfume-3d-frontend/` e a aplicacao FastAPI em `perfume-3d-backend/`, que tambem contem o Compose e o servico Hunyuan. O backend usa PostgreSQL para persistencia, storage local para uploads/modelos `.glb` e expoe arquivos estaticos por `/files` e `/templates`.

```text
Flutter app (`perfume-3d-frontend/`)
  |  HTTP JSON/multipart via Dio
  v
FastAPI backend (`perfume-3d-backend/`)
  |-- /health
  |-- /captures
  |-- /sales
  |-- /files
  |-- /templates
  |
  |  SQLAlchemy async / asyncpg
  v
PostgreSQL 16 (docker-compose service postgres)

Hunyuan Docker service (docker/hunyuan/)
  |-- GET /health
  |-- POST /generate
  |
  +-- GPU NVIDIA + cache Hugging Face em volume Docker
```

O servico Hunyuan roda em **processo separado**: o container expoe HTTP em `7860` e carrega os modelos de IA dentro dele. No fluxo HTTP principal `POST /captures` com `PIPELINE_MODE=integrated` (**default**), o backend **chama** esse container: a factory `build_pipeline()` instancia o `IntegratedPipeline`, que usa o `Hunyuan3DProcessor` (cliente `httpx`) como stage de geracao 3D. Os modos `fake` (cubo) e `template` (Blender) nao tocam o container — uteis para dev sem GPU. O backend Python nao importa `torch`/ML pesado; toda inferencia fica no container (fontes: `docker-compose.yml`, `docker/hunyuan/server.py`, `app/main.py`, `app/modules/captures/pipeline.py`, `app/modules/captures/processor.py`).

## Por que existe

Esta visao existe para separar mentalmente tres coisas: (1) o **pipeline 3D** do `POST /captures` — default `integrated` (Hunyuan + cache CLIP + pos-processamento), com `fake`/`template` como alternativas; (2) o **modulo comercial** `/sales`; e (3) o **servico Hunyuan** em Docker, que roda em processo separado e e chamado por HTTP.

## Stack/dependencias

| Componente | Responsabilidade | Fontes |
|---|---|---|
| Flutter | UI, captura, vendas, polling e visualizacao 3D | `../perfume-3d-frontend/lib/app/`, `../perfume-3d-frontend/pubspec.yaml` |
| Dio | Cliente HTTP para `/captures/*` e `/sales/*` | `../perfume-3d-frontend/lib/core/network/`, `../perfume-3d-frontend/lib/features/sales/data/` |
| FastAPI | API HTTP, CORS, routers e static files | `app/main.py` |
| SQLAlchemy async | Engine/session para Postgres e modelos `captures` | `app/database.py`, `app/modules/captures/models.py` |
| SQL textual | Operacoes comerciais sobre schema `sales` preexistente | `app/modules/sales/repository.py` |
| Docker Compose | Postgres e Hunyuan | `docker-compose.yml` |

## Estrutura

O backend monta tres routers principais: `health_router`, `captures_router` e `sales_router` em `app/main.py`. O modulo `captures` tem service, queue, repository, processor e schemas proprios; o modulo `sales` concentra contrato e SQL em `schemas.py`, `router.py` e `repository.py`.

No frontend, o roteamento e centralizado em `GoRouter`; a aplicacao abre em `/` com `HomeDashboardPage`. As features principais ficam em `perfume-3d-frontend/lib/features/`.

## Como rodar/usar

Fluxo de captura 3D:

1. O Flutter envia `images` e `views` paralelos por `POST /captures`.
2. O backend cria um `CaptureJob`, salva uploads em `storage/uploads/<job_id>/` e coloca o job na fila.
3. O processor gera `storage/models/<job_id>.glb` e o status passa a `completed` com `modelUrl` absoluto.
4. O Flutter faz polling em `/captures/{jobId}/status` e abre o modelo no viewer quando recebe `modelUrl`.

Fluxo comercial:

1. O Flutter tenta carregar `/sales/snapshot` no boot do `SalesController`.
2. Criacao de clientes/produtos, estoque, vendas e recebimentos aguardam a
   confirmacao de `/sales/*` antes de atualizar o estado local.
3. O backend le e escreve no schema comercial via SQL textual.

## Pontos de atencao

- O Hunyuan tem endpoints proprios (`/health`, `/generate`) e nao compartilha processo Python com o backend principal (fontes: `docker/hunyuan/server.py`, `docker/hunyuan/entrypoint.sh`).
- O compose nao declara `depends_on` entre `postgres` e `hunyuan`; sao servicos independentes no mesmo arquivo (fonte: `docker-compose.yml`).
- `PIPELINE_MODE` aceita `fake`, `template` ou `integrated` (**default**) nas settings atuais; o antigo `PROCESSOR_TYPE` e lido como alias com aviso de deprecation (fonte: `app/config.py`).
- A URL do backend no Flutter deve ser configurada por `--dart-define=BACKEND_BASE_URL=...` quando `localhost` nao servir para o dispositivo.
