# 06 — Bootstrap e lifespan

O ponto de entrada da aplicação é `app/main.py`, que expõe `app = create_app()` e, em produção, o `production_lifespan` assíncrono.

## `create_app()`

- Aceita `storage_dir` opcional (testes usam diretório temporário) e `lifespan` opcional.
- Cria `storage_dir/uploads` e `storage_dir/models` se não existirem.
- Registra: middleware CORS, exception handlers, routers `health` e `captures`, monta arquivos estáticos.
- **Mounts HTTP:**
  - `/files` → `StaticFiles` em `storage_root` (uploads, models, `model_viewer.html`, etc.)
  - `/templates` → `StaticFiles` em `settings.templates_dir` (`assets/templates/normalized`), **somente se o diretório existir** — expõe cada `<template_id>.glb` em `/templates/<arquivo>.glb` para debug e viewer local.

## `production_lifespan`

Executado na subida do Uvicorn, **antes** de aceitar tráfego:

1. `configure_logging()` — log em stdout.
2. `await create_all()` — cria tabelas SQLAlchemy no Postgres (sem Alembic no MVP).
3. `LocalStorage().ensure_dirs()` — `uploads/` e `models/`.
4. `build_processor()` / `build_classifier()` / `build_color_detector()` — leem `Settings` (`.env`).
5. `CaptureService(session_factory, storage, processor, queue, classifier, color_detector)`.
6. `app.state.capture_service` e `app.state.queue = queue`.
7. `queue.start(service.process_job)` — inicia o worker assíncrono.
8. Log: `Backend pronto em <host>:<port> (processor=..., classifier=..., color=...)`.

No **shutdown** (yield final do lifespan):

- `await queue.stop()` — cancela o worker.
- `await engine.dispose()` — fecha pool do SQLAlchemy.

## Testes sem Postgres

A factory `create_app` permite `lifespan=None` e preencher `app.state` manualmente em testes, usando SQLite em memória ou arquivos temporários (ver [`conftest.py`](../tests/conftest.py) e [14 — Testes](14-testes.md)).

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md)
- [07 — Camada `core`](07-camada-core.md) (`config` e banco)
- [13 — Endpoints HTTP](13-endpoints-http.md) (rotas e URLs estáticas)
