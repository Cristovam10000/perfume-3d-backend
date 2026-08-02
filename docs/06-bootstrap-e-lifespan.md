# 06 — Bootstrap e lifespan

> **O que você vai aprender neste doc**
> - A diferença entre `create_app()` (montar a app) e `production_lifespan` (subir os recursos).
> - O que existe no `app.state` em runtime (o `CaptureService` e a fila).
> - Por que a factory aceita `lifespan=None` — o truque que permite testar sem Postgres/worker.
>
> **Pré-requisitos:** [05 - Arquitetura](05-arquitetura.md). Veja o código em [`app/main.py`](../app/main.py).

O ponto de entrada da aplicação é `app/main.py`, que expõe `app = create_app()` e, em produção, o `production_lifespan` assíncrono.

## `create_app()`

- Aceita `storage_dir` opcional (testes usam diretório temporário) e `lifespan` opcional.
- Cria `storage_dir/uploads`, `storage_dir/models` e `storage_dir/cache` se não existirem.
- Registra: middleware CORS, exception handlers, routers `health`, `captures` e `sales`, monta arquivos estáticos.
- **Mounts HTTP:**
  - `/files` → `StaticFiles` em `storage_root` (uploads, models, `model_viewer.html`, etc.)
  - `/templates` → `StaticFiles` em `settings.templates_dir` (`assets/templates/normalized`), **somente se o diretório existir** — expõe cada `<template_id>.glb` em `/templates/<arquivo>.glb` para debug e viewer local.

## `production_lifespan`

Executado na subida do Uvicorn, **antes** de aceitar tráfego:

1. `configure_logging()` — log em stdout.
2. `await create_all()` — cria tabelas SQLAlchemy no Postgres (`capture_jobs`, `capture_images`, `modelos_3d_universais`). Sem Alembic no MVP.
3. `await ensure_sales_schema(engine)` — `ALTER TABLE IF EXISTS` para campos do módulo `sales`.
4. `await ensure_captures_schema(engine)` — migração incremental do captures: `modelo_universal_id` (+FK) em `modelos_3d_produto`, `product_id` em `capture_jobs`, `view` em `capture_images`. Idempotente — `create_all()` não toca em tabelas que não criou, por isso esses `ALTER TABLE`.
5. `LocalStorage().ensure_dirs()` — `uploads/`, `models/`, `cache/`.
6. `build_pipeline()` — fabrica o `Processor` raiz conforme `PIPELINE_MODE` no `.env`:
   - `fake` → `FakeProcessor()`
   - `integrated` → `IntegratedPipeline(...)` com todas as factories de stage (`build_image_preprocessor`, `build_background_remover`, `build_embedder`, `build_model_cache`, `build_hunyuan`, `build_mesh_refiner`, `build_transparency_classifier`, `build_label_extractor`, `build_label_upscaler`, `build_label_projector`).
7. `CaptureService(session_factory, storage, pipeline, queue)`.
8. `app.state.capture_service` e `app.state.queue = queue`.
9. `queue.start(service.process_job)` — inicia o worker assíncrono.
10. Log: `Backend pronto em <host>:<port> (pipeline=<mode>, cache_enabled=<bool>, hunyuan_url=<url>)`.

No **shutdown** (yield final do lifespan):

- `await queue.stop()` — cancela o worker.
- `await engine.dispose()` — fecha pool do SQLAlchemy.

## Testes sem Postgres

A factory `create_app` permite `lifespan=None` e preencher `app.state` manualmente em testes, usando SQLite em memória ou arquivos temporários (ver [`conftest.py`](../tests/conftest.py) e [14 — Testes](14-testes.md)).

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md)
- [07 — Camada `core`](07-camada-core.md) (`config` e banco)
- [13 — Endpoints HTTP](13-endpoints-http.md) (rotas e URLs estáticas)
