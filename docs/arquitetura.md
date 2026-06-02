# Arquitetura

## Visao geral

A arquitetura atual e um conjunto de aplicacoes e servicos co-localizados nesta pasta local: um app Flutter em `front/`, uma aplicacao backend FastAPI modular em `back/` e servicos auxiliares em Docker. O backend usa PostgreSQL para persistencia, storage local para uploads/modelos `.glb` e expõe arquivos estaticos por `/files` e `/templates` (fontes: `front/pubspec.yaml`, `back/app/main.py`, `back/app/database.py`, `back/app/storage/local_storage.py`, `docker-compose.yml`).

```text
Flutter app (front/)
  |  HTTP JSON/multipart via Dio
  v
FastAPI backend (back/)
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

O servico Hunyuan roda em **processo separado**: o container expoe HTTP em `7860` e carrega os modelos de IA dentro dele. No fluxo HTTP principal `POST /captures` com `PIPELINE_MODE=integrated` (**default**), o backend **chama** esse container: a factory `build_pipeline()` instancia o `IntegratedPipeline`, que usa o `Hunyuan3DProcessor` (cliente `httpx`) como stage de geração 3D. Os modos `fake` (cubo) e `template` (Blender) não tocam o container — úteis para dev sem GPU. O backend Python não importa `torch`/ML pesado; toda inferência fica no container (fontes: `docker-compose.yml`, `docker/hunyuan/server.py`, `back/app/main.py`, `back/app/modules/captures/pipeline.py`, `back/app/modules/captures/processor.py`).

## Por que existe

Esta visao existe para separar mentalmente tres coisas: (1) o **pipeline 3D** do `POST /captures` — default `integrated` (Hunyuan + cache CLIP + pós-proc), com `fake`/`template` como alternativas; (2) o **modulo comercial** `/sales`; e (3) o **servico Hunyuan** em Docker, que roda em processo separado e é chamado por HTTP (fontes: `back/app/main.py`, `back/app/modules/captures/pipeline.py`, `back/app/modules/captures/processor.py`, `back/app/modules/sales/router.py`, `docker/hunyuan/server.py`).

## Stack/dependencias

| Componente | Responsabilidade | Fontes |
|---|---|---|
| Flutter | UI, captura, vendas, polling e visualizacao 3D | `front/lib/app/app.dart`, `front/lib/app/router/app_router.dart`, `front/pubspec.yaml` |
| Dio | Cliente HTTP para `/captures/*` e `/sales/*` | `front/lib/core/network/dio_client.dart`, `front/lib/features/sales/data/sales_repository.dart` |
| FastAPI | API HTTP, CORS, routers e static files | `back/app/main.py` |
| SQLAlchemy async | Engine/session para Postgres e modelos `captures` | `back/app/database.py`, `back/app/modules/captures/models.py` |
| SQL textual | Operacoes comerciais sobre schema `sales` preexistente | `back/app/modules/sales/repository.py` |
| Docker Compose | Postgres e Hunyuan | `docker-compose.yml` |

## Estrutura

O backend monta tres routers principais: `health_router`, `captures_router` e `sales_router` (fonte: `back/app/main.py`). O modulo `captures` tem service, queue, repository, processor e schemas proprios (fontes: `back/app/modules/captures/service.py`, `back/app/modules/captures/queue.py`, `back/app/modules/captures/repository.py`, `back/app/modules/captures/schemas.py`). O modulo `sales` concentra contrato e SQL em `schemas.py`, `router.py` e `repository.py` (fontes: `back/app/modules/sales/schemas.py`, `back/app/modules/sales/router.py`, `back/app/modules/sales/repository.py`).

No frontend, o roteamento e centralizado em `GoRouter`; a aplicacao abre em `/` com `HomeDashboardPage` (fontes: `front/lib/app/router/app_routes.dart`, `front/lib/app/router/app_router.dart`). As features principais ficam em `front/lib/features/product_capture`, `front/lib/features/processing`, `front/lib/features/product_viewer` e `front/lib/features/sales` (fonte: arvore `front/lib/features/`).

## Como rodar/usar

Fluxo de captura 3D:

1. O Flutter envia imagens por `POST /captures` com campo multipart `images` (fontes: `front/lib/features/product_capture/data/capture_repository.dart`, `back/app/modules/captures/router.py`).
2. O backend cria um `CaptureJob`, salva uploads em `storage/uploads/<job_id>/` e coloca o job na fila (fontes: `back/app/modules/captures/service.py`, `back/app/storage/local_storage.py`, `back/app/modules/captures/queue.py`).
3. O processor gera `storage/models/<job_id>.glb` e o status passa a `completed` com `modelUrl` absoluto (fontes: `back/app/modules/captures/service.py`, `back/app/storage/local_storage.py`, `back/app/modules/captures/router.py`).
4. O Flutter faz polling em `/captures/{jobId}/status` e abre o modelo no viewer quando recebe `modelUrl` (fontes: `front/lib/features/processing/data/processing_repository.dart`, `front/lib/features/processing/presentation/state/processing_controller.dart`).

Fluxo comercial:

1. O Flutter tenta carregar `/sales/snapshot` no boot do `SalesController` (fonte: `front/lib/features/sales/data/sales_repository.dart`).
2. Criacao de produto, ajuste de estoque e criacao de venda atualizam primeiro o estado local e depois tentam sincronizar com `/sales/*` (fonte: `front/lib/features/sales/data/sales_repository.dart`).
3. O backend le e escreve no schema comercial via SQL textual (fonte: `back/app/modules/sales/repository.py`).

## Pontos de atencao

- O Hunyuan tem endpoints proprios (`/health`, `/generate`) e nao compartilha processo Python com o backend principal (fontes: `docker/hunyuan/server.py`, `docker/hunyuan/entrypoint.sh`).
- O compose nao declara `depends_on` entre `postgres` e `hunyuan`; sao servicos independentes no mesmo arquivo (fonte: `docker-compose.yml`).
- `PIPELINE_MODE` aceita `fake`, `template` ou `integrated` (**default**) nas settings atuais; o antigo `PROCESSOR_TYPE` é lido como alias com aviso de deprecation (fonte: `back/app/config.py`).
- A URL do backend no Flutter deve ser configurada por `--dart-define=BACKEND_BASE_URL=...` quando `localhost` nao servir para o dispositivo (fonte: `front/lib/core/constants/app_constants.dart`).
