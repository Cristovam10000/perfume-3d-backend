# 12 — Armazenamento local e banco de dados

## Armazenamento em disco — `LocalStorage`

Raiz: `settings.storage_root` (default `./storage`), resolvida para caminho absoluto.

| Caminho | Conteúdo | Git |
|---------|----------|-----|
| `uploads/<job_id>/<filename>` | Fotos enviadas no `POST /captures` | ignorado (`.gitignore`) |
| `models/<job_id>.glb` | Modelo 3D gerado pelo `Processor` | ignorado |
| `model_viewer.html` (na raiz de `storage/`) | Viewer HTML de debug | versionado (exceção) |

- `model_public_path(job_id)` retorna a string `"/files/models/{job_id}.glb"`, usada no campo `model_path` persistido e depois exposta no status como URL absoluta.

## Servir ficheiros — `StaticFiles`

- O mount `/files` aponta para a mesma raiz de `storage`. O cliente (Flutter) faz `GET` nessa URL; suporta cache e requisições em intervalo (range) conforme o Starlette.

## PostgreSQL e schema

- Tabelas criadas com `Base.metadata.create_all` no startup (sem Alembic no MVP):
  - **`capture_jobs`**: `id` (PK string UUID), `status`, `message`, `model_path`, `error`, `created_at`, `updated_at`
  - **`capture_images`**: `id`, `job_id` (FK com cascade), `filename`, `path`
- O status é guardado como string, alinhado com o enum `CaptureStatus` no código.
- O driver assíncrono é `asyncpg` via URL `postgresql+asyncpg://...` em `Settings.database_url`.

## Testes

- A suíte de testes usa **SQLite** assíncrono (fixture em `conftest.py`), não requer Docker do Postgres. Ver [14 — Testes](14-testes.md).

## Leituras relacionadas

- [07 — Camada `core`](07-camada-core.md) (config e URL da base)
- Código: [`app/storage/local_storage.py`](../app/storage/local_storage.py), [`app/modules/captures/models.py`](../app/modules/captures/models.py)
