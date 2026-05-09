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

### Schema do módulo `captures`

- Tabelas criadas com `Base.metadata.create_all` no startup (sem Alembic no MVP):
  - **`capture_jobs`**: `id` (PK string UUID), `status`, `message`, `model_path`, `error`, `created_at`, `updated_at`
  - **`capture_images`**: `id`, `job_id` (FK com cascade), `filename`, `path`
- O status é guardado como string, alinhado com o enum `CaptureStatus` no código.

### Schema do módulo `sales`

O módulo `sales/` usa um schema **pré-existente** (criado via `psql` manual ou script externo, não controlado pelo backend). O bootstrap do FastAPI chama [`ensure_sales_schema(engine)`](../app/modules/sales/repository.py) no startup, que aplica apenas `ALTER TABLE IF EXISTS … ADD COLUMN IF NOT EXISTS …` para garantir compatibilidade com instalações antigas — **não cria tabelas do zero**.

Tabelas referenciadas pelo `SalesRepository` (todas em snake_case e em português, refletindo o domínio comercial brasileiro):

| Tabela | Conteúdo |
|---|---|
| `clientes` | Clientes ativos do app comercial. |
| `produtos` | Catálogo de perfumes. Colunas garantidas pelo `ensure_sales_schema`: `custo numeric(10,2)`, `estoque_minimo integer`, `volume_ml integer`, `frasco_color_value bigint`. Possui flag `possui_modelo_3d boolean` para integração com captures. |
| `vendas` | Cabeçalho da venda (cliente, data, total, parcelado). |
| `itens_venda` | Linhas de cada venda (produto, quantidade, preço unitário). |
| `parcelas` | Parcelas geradas para vendas a prazo. |
| `eventos_parcela` | Histórico de eventos por parcela (vencida, paga, renegociada). |
| `pagamentos` | Pagamentos recebidos. |
| `notificacoes` | Notificações comerciais (parcelas vencendo, etc). |
| `resumo_financeiro_cliente` | Tabela de resumo materializada por cliente. |

> **Decisão arquitetural:** o `SalesRepository` usa SQL textual (`sqlalchemy.text`) em vez de modelos ORM, deliberadamente — o schema comercial é grande, estável e mais legível em SQL puro do que em mappings declarativos. Captures usa SQLAlchemy 2.0 (typed mappings). Ambos compartilham a mesma `AsyncEngine`/`SessionFactory`.

### Driver assíncrono

- O driver assíncrono é `asyncpg` via URL `postgresql+asyncpg://...` em `Settings.database_url`.
- Captures e sales compartilham a mesma engine/session — modelo monolítico modular.

## Testes

- A suíte de testes do `captures` usa **SQLite** assíncrono (fixture em `conftest.py`), não requer Docker do Postgres.
- O `sales` ainda não tem cobertura de testes automatizada (apenas exercitado manualmente via app Flutter contra um Postgres real). Ver [14 — Testes](14-testes.md).

## Leituras relacionadas

- [07 — Camada `core`](07-camada-core.md) (config e URL da base)
- Código: [`app/storage/local_storage.py`](../app/storage/local_storage.py), [`app/modules/captures/models.py`](../app/modules/captures/models.py), [`app/modules/sales/repository.py`](../app/modules/sales/repository.py)
